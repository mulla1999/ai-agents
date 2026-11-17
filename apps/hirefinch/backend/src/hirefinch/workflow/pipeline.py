"""Orchestrator: moves each job forward one checkpointed stage at a time.

    discovered → evaluated → shortlisted → resume ready → application prepared
      → (approval) → submitted → recruiter outreach → notifications

Every stage commits before the next starts, so a crash resumes from the last completed stage,
and a stage that already happened (a submission, an email) is never repeated because a later
stage failed. ``advance`` is safe to call any number of times on any job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..connectors.base import ConnectorAuthError, ConnectorError
from ..db import Application, EmailDraft, JobPosting, JobSource, JobStatus, RecruiterContact, aware, utcnow
from ..errors import ServiceError
from ..runtime import UserRuntime as Runtime
from ..services import applications, outreach
from ..services.audit import record
from ..services.jobs import ensure_sources, evaluate_job, latest_match, load_candidate, run_source
from ..services.notify import notify_connector_auth, notify_high_priority, notify_resume_ready
from ..services.integrations import platform_config
from ..services.settings_store import get_policy_state, get_preferences
from ..services.tailoring import generate, latest_version
from .states import transition
from .timing import discovery_allowed, in_window

log = logging.getLogger(__name__)

ACTIVE_STATES = (
    JobStatus.DISCOVERED, JobStatus.MATCH_EVALUATED, JobStatus.SHORTLISTED, JobStatus.RESUME_READY,
    JobStatus.READY_TO_APPLY, JobStatus.APPLIED,
)


@dataclass
class RunReport:
    sources: dict[str, str] = field(default_factory=dict)
    new_jobs: int = 0
    advanced: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


async def advance(db: AsyncSession, rt: Runtime, job: JobPosting) -> list[str]:
    """Run every stage the job is ready for. Returns the stages completed."""
    done: list[str] = []
    if job.user_id != rt.user_id:  # a runtime only ever acts for its own user
        raise ServiceError("not_found", "job not found", 404)
    state = await get_policy_state(db, job.user_id)
    policy = state.policy
    if state.emergency_stop:
        return done
    if job.is_duplicate:
        return done  # the original carries the workflow

    if job.status == JobStatus.DISCOVERED:
        if await load_candidate(db, job.user_id) is None:
            return done
        await evaluate_job(db, job)
        await db.commit()
        done.append("evaluated")

    if job.status == JobStatus.MATCH_EVALUATED:
        match = await latest_match(db, job.id)
        flags = job.flags or {}
        not_shortlisted = (match is None or match.band in ("disqualified", "review", "low")
                           or match.score < policy.shortlist_min_score or job.liveness == "expired"
                           or flags.get("suspicious") or flags.get("prompt_injection"))
        if not_shortlisted:
            # No tailored resume will be made. If the job has a verified email address, offer an email
            # with your base resume instead (drafted for approval unless automatic outreach is on).
            if await _base_resume_email(db, rt, job, match, policy):
                done.append("base_resume_email")
            return done
        await transition(db, job, JobStatus.SHORTLISTED, reason=f"score {match.score:g} ≥ {policy.shortlist_min_score}")
        if match.band == "high":
            await notify_high_priority(db, job, match.score)
        await db.commit()
        done.append("shortlisted")

    if job.status == JobStatus.SHORTLISTED:
        match = await latest_match(db, job.id)
        if match is None or match.score < policy.tailor_min_score:
            return done
        version = await generate(db, rt.settings, job, rt.llm)
        await notify_resume_ready(db, job, version)
        await db.commit()
        done.append("resume")

    if job.status == JobStatus.RESUME_READY:
        await applications.prepare(db, rt, job)
        await db.commit()
        done.append("prepared")

    if job.status == JobStatus.READY_TO_APPLY:
        app = await db.scalar(select(Application).where(Application.job_id == job.id))
        if app is not None and app.mode == "automatic" and app.approved_at is None:
            if applications.is_due(app, policy):  # review hold over and a send window open
                await applications.submit(db, rt, app, trigger="automatic")
                done.append("submitted")
        elif app is not None and app.approved_at is not None:
            await applications.submit(db, rt, app, trigger="approved")
            done.append("submitted")

    if job.status == JobStatus.APPLIED:
        contacts = (await db.scalars(select(RecruiterContact).where(RecruiterContact.job_id == job.id,
                                                                     RecruiterContact.verified.is_(True)))).all()
        for contact in contacts[:1]:  # one recruiter per job
            draft = await outreach.draft(db, rt, job, contact)
            if draft.status != "draft":
                continue
            if policy.auto_send_outreach:
                await outreach.schedule(db, draft, policy)
                done.append("outreach_scheduled")
            else:
                await outreach.request_approval(db, draft, "recruiter emails are sent only after your review")
                done.append("outreach_drafted")
        await db.commit()
    return done


async def _base_resume_email(db: AsyncSession, rt: Runtime, job: JobPosting, match, policy) -> bool:  # noqa: ANN001
    flags = job.flags or {}
    prefs = await get_preferences(db, job.user_id)
    # Only a real match: the shortlist score (roles outside engineering are capped below it), not just "review".
    if (match is None or match.band in ("disqualified", "low") or match.score < max(prefs.thresholds.review, policy.shortlist_min_score)
            or flags.get("suspicious") or flags.get("prompt_injection") or job.liveness == "expired"):
        return False
    if await latest_version(db, job.id) is not None:
        return False  # a tailored resume exists: the normal path applies
    contact = await db.scalar(select(RecruiterContact).where(RecruiterContact.job_id == job.id,
                                                             RecruiterContact.verified.is_(True)).order_by(RecruiterContact.id))
    if contact is None:
        return False
    draft = await outreach.draft(db, rt, job, contact)
    if draft.status != "draft" or draft.attachment_source != "master":
        return False
    if policy.auto_send_outreach:
        await outreach.schedule(db, draft, policy)
    else:
        await outreach.request_approval(db, draft, "this job has an email address but no tailored resume: "
                                                   "review the email with your base resume")
    await db.commit()
    return True


def _due(source: JobSource, default_minutes: int, floor: int = 0) -> bool:
    if source.last_run_at is None:
        return True
    minutes = max(source.schedule_minutes or default_minutes, floor)
    return aware(source.last_run_at) + timedelta(minutes=minutes) <= utcnow()  # type: ignore[operator]


async def run_discovery(rt: Runtime, *, source_key: str | None = None, scheduled: bool = False) -> RunReport:
    report = RunReport()
    async with rt.sessionmaker() as db:
        state = await get_policy_state(db, rt.user_id)
        if state.emergency_stop or (scheduled and state.paused):
            report.errors.append("automation is paused or stopped")
            return report
        if scheduled and not discovery_allowed(utcnow(), state.policy):
            return report  # outside discovery hours
        await ensure_sources(db, rt.user_id, mock=rt.settings.mock_enabled)  # a new account starts with the defaults
        mine = JobSource.user_id == rt.user_id
        query = select(JobSource).where(mine, JobSource.enabled.is_(True))
        if source_key:
            query = select(JobSource).where(mine, JobSource.key == source_key)
        floor = int((await platform_config(db, "limits"))["min_discovery_minutes"])
        interval = max(state.policy.discovery_interval_minutes, floor)
        for source in (await db.scalars(query)).all():
            if scheduled and (source.auth_ok is False or not _due(source, interval, floor)):
                continue
            try:
                stats = await run_source(db, rt.settings, rt.fetcher, source, rt.credentials)
                report.sources[source.key] = f"{stats.new} new"
                report.new_jobs += stats.new
            except ConnectorAuthError as exc:
                report.sources[source.key] = "auth failed"
                await notify_connector_auth(db, rt.user_id, source.name, str(exc))
            except ConnectorError as exc:
                report.sources[source.key] = "failed"
                report.errors.append(f"{source.key}: {exc}")
            except ServiceError as exc:
                report.sources[source.key] = exc.message
            await db.commit()
    await advance_all(rt, report)
    return report


async def advance_all(rt: Runtime, report: RunReport | None = None, limit: int = 200) -> RunReport:
    report = report or RunReport()
    async with rt.sessionmaker() as db:
        # New jobs first, then newest first: older evaluated jobs must not use up the batch.
        new_first = case((JobPosting.status == JobStatus.DISCOVERED, 0), else_=1)
        ids = (await db.scalars(select(JobPosting.id).where(JobPosting.user_id == rt.user_id,
                                                            JobPosting.status.in_(ACTIVE_STATES))
                                .order_by(new_first, JobPosting.id.desc()).limit(limit))).all()
    for job_id in ids:
        async with rt.sessionmaker() as db:
            job = await db.get(JobPosting, job_id)
            if job is None:
                continue
            try:
                for stage in await advance(db, rt, job):
                    report.advanced[stage] = report.advanced.get(stage, 0) + 1
            except ServiceError as exc:
                await db.rollback()
                report.errors.append(f"job {job_id}: {exc.message}")
            except Exception as exc:  # one bad job must not stop the run
                log.exception("pipeline failed for job %s", job_id)
                await db.rollback()
                async with rt.sessionmaker() as db2:
                    await record(db2, rt.user_id, "pipeline.error", f"job {job_id}: {exc.__class__.__name__}", level="error",
                                 entity=("job", job_id))
                    await db2.commit()
                report.errors.append(f"job {job_id}: {exc.__class__.__name__}")
    return report


async def dispatch_due(rt: Runtime) -> dict[str, int]:
    """Send what is due: automatic applications and scheduled recruiter emails whose review hold has
    passed, while a send window is open. Runs every few minutes from the scheduler."""
    sent = {"applications": 0, "emails": 0}
    async with rt.sessionmaker() as db:
        state = await get_policy_state(db, rt.user_id)
        if state.emergency_stop or state.paused or not in_window(utcnow(), state.policy):
            return sent
        apps = (await db.scalars(select(Application).join(JobPosting).where(
            Application.user_id == rt.user_id, JobPosting.status == JobStatus.READY_TO_APPLY,
            Application.mode == "automatic", Application.approved_at.is_(None),
            Application.scheduled_for <= utcnow()))).all()
        for app in apps:
            try:
                await applications.submit(db, rt, app, trigger="automatic")
                sent["applications"] += 1
            except ServiceError as exc:
                log.info("automatic application %s not sent: %s", app.id, exc.message)
                await db.rollback()
        drafts = (await db.scalars(select(EmailDraft).where(
            EmailDraft.user_id == rt.user_id, EmailDraft.status == "scheduled", EmailDraft.scheduled_for <= utcnow()))).all()
        for draft in drafts:
            try:
                await outreach.send(db, rt, draft, actor="system")
                sent["emails"] += 1
            except ServiceError as exc:
                draft.status = "draft"  # back to you, with the reason
                await outreach.request_approval(db, draft, exc.message)
                await db.commit()
    return sent

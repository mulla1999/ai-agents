"""Application preparation, approval and execution.

Safety properties, each covered by tests:

* one application per job (unique constraint) and never one for a duplicate of a job applied to
* an attempt row is committed *before* the external call; after a crash or timeout it becomes
  UNKNOWN and the route is asked to verify before anything is retried
* a job is APPLIED only with evidence: a confirmation (confirmed), or a mail server's acceptance /
  your own word (uncertain). A click is not evidence.
* the attached file is the exact resume version recorded on the application, checked by SHA-256
* nothing is submitted during an emergency stop, or automatically outside the configured policy
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..applications.answers import prepare_answer
from ..applications.policy import Decision, PolicyInput, decide
from ..applications.routes import NeedsPerson, Package, RouteError, Submission, SubmissionTimeout
from ..db import (
    Application,
    ApplicationAnswer,
    ApplicationAttempt,
    ApprovalRequest,
    AttemptStatus,
    JobPosting,
    JobStatus,
    Outcome,
    ResumeVersion,
    aware,
    utcnow,
)
from ..domain import ApplicationMode
from ..errors import ServiceError
from ..jobs.matching import title_similarity
from ..notifications.email import Attachment
from ..notifications.outbox import enqueue
from ..runtime import UserRuntime as Runtime
from ..text import sha256_file, slug
from ..workflow.states import SUBMITTED_STATES, transition
from ..workflow.timing import in_window, next_send_time
from .audit import record
from .integrations import platform_config
from .jobs import latest_match, load_candidate
from ..text import format_phone, full_url, resume_filename
from .email_compose import EmailFacts, _signature, plain_text
from .notify import notify_application_result, notify_approval_needed, notify_auto_scheduled
from .settings_store import get_policy_state, get_preferences, get_profile
from .tailoring import latest_version

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
_ALREADY_SUBMITTED = (AttemptStatus.SUCCEEDED, AttemptStatus.UNCERTAIN)


def route_for(rt: Runtime, name: str):  # noqa: ANN201
    route = rt.routes.get(name)
    if route is None:
        raise ServiceError("route_unavailable", f"the '{name}' route is not available here", 409)
    return route


async def applied_counts(db: AsyncSession, user_id: int) -> tuple[int, int]:
    now = utcnow()
    mine = Application.user_id == user_id
    day = await db.scalar(select(func.count(Application.id)).where(mine, Application.submitted_at >= now - timedelta(days=1)))
    week = await db.scalar(select(func.count(Application.id)).where(mine, Application.submitted_at >= now - timedelta(days=7)))
    return int(day or 0), int(week or 0)


async def previously_applied(db: AsyncSession, job: JobPosting) -> bool:
    """True if this job, its original, or any duplicate/repost of the same original was applied to."""
    root = job.duplicate_of_id or job.id
    related = select(JobPosting.id).where(or_(JobPosting.id == root, JobPosting.duplicate_of_id == root))
    rows = (await db.scalars(select(JobPosting).where(JobPosting.id.in_(related), JobPosting.id != job.id))).all()
    return any(r.status in SUBMITTED_STATES for r in rows)


async def decision_for(db: AsyncSession, rt: Runtime, job: JobPosting, app: Application) -> Decision:
    state = await get_policy_state(db, job.user_id)
    match = await latest_match(db, job.id)
    version = await db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    prefs = await get_preferences(db, job.user_id)
    day, week = await applied_counts(db, job.user_id)
    route = route_for(rt, app.route)
    return decide(PolicyInput(
        mode=state.policy.mode, policy=state.policy,
        score=match.score if match else None, band=match.band if match else None,
        recommended=bool(match and match.recommended),
        role_fit=title_similarity(job.title, prefs.target_roles)[0],
        route=app.route, route_ready=route.ready(),
        expired=job.liveness == "expired" or job.status == JobStatus.EXPIRED,
        previous_application=await previously_applied(db, job),
        resume_valid=bool(version and version.valid),
        unanswered=[a.question for a in app.answers if a.needs_user],
        flags=job.flags or {}, applied_today=day, applied_this_week=week, emergency_stop=state.emergency_stop,
    ))


async def prepare(db: AsyncSession, rt: Runtime, job: JobPosting, *, actor: str = "system") -> Application:
    """Create (or refresh) the application for a job with a ready resume, then route it to
    approval or, when every automatic condition holds, to ready-to-apply."""
    if job.status not in (JobStatus.RESUME_READY, JobStatus.AWAITING_APPROVAL, JobStatus.NEEDS_MANUAL):
        raise ServiceError("bad_state", f"the job is '{job.status}'; generate a resume first", 409)
    version = await latest_version(db, job.id)
    if version is None:
        raise ServiceError("no_resume_version", "no validated tailored resume for this job", 409)
    loaded = await load_candidate(db, job.user_id)
    if loaded is None:
        raise ServiceError("no_resume", "upload a master resume first", 409)
    candidate, _ = loaded
    profile = await get_profile(db, job.user_id)
    state = await get_policy_state(db, job.user_id)

    app = await db.scalar(select(Application).where(Application.job_id == job.id))
    if app is None:
        # Relationships set up front: async sessions cannot lazy-load them later.
        app = Application(user_id=job.user_id, job_id=job.id, job=job, route=job.apply_method, mode=state.policy.mode.value,
                          answers=[], attempts=[])
        db.add(app)
        await db.flush()
    elif app.outcome != Outcome.PENDING:
        raise ServiceError("already_submitted", "this application was already submitted", 409)
    app.resume_version_id = version.id
    app.route = job.apply_method
    existing = {a.question: a for a in app.answers}
    for question in job.questions or []:
        if question in existing and existing[question].source == "user":
            continue  # keep what you typed
        prepared = prepare_answer(question, profile, candidate, company=job.company)
        row = existing.get(question) or ApplicationAnswer(application_id=app.id, question=question[:1000])
        row.category, row.answer, row.source = prepared.category, prepared.answer, prepared.source
        row.sensitive, row.needs_user = prepared.sensitive, prepared.needs_user
        if question not in existing:
            app.answers.append(row)
    await db.flush()

    decision = await decision_for(db, rt, job, app)
    app.pause_reasons = decision.manual_reasons + decision.auto_blockers
    if decision.automatic:
        app.mode = ApplicationMode.AUTOMATIC.value
        if job.status != JobStatus.READY_TO_APPLY:
            await transition(db, job, JobStatus.READY_TO_APPLY, reason="meets every automatic-application condition")
        if app.scheduled_for is None:
            policy = state.policy
            app.scheduled_for = next_send_time(utcnow() + timedelta(minutes=policy.auto_review_minutes), policy)
            await notify_auto_scheduled(db, job, app, policy.timezone)
    else:
        app.mode = ApplicationMode.SUPERVISED.value
        if job.status != JobStatus.AWAITING_APPROVAL:
            await transition(db, job, JobStatus.AWAITING_APPROVAL,
                             reason=(decision.manual_reasons or decision.auto_blockers)[0], actor=actor)
        pending = await db.scalar(select(ApprovalRequest).where(
            ApprovalRequest.kind == "application", ApprovalRequest.target_id == app.id, ApprovalRequest.status == "pending"))
        if pending is None:
            db.add(ApprovalRequest(user_id=job.user_id, kind="application", job_id=job.id, target_id=app.id, reasons=app.pause_reasons))
            await notify_approval_needed(db, job, app.pause_reasons)
        else:
            pending.reasons = app.pause_reasons
    await record(db, app.user_id, "application.prepared", f"application for job {job.id} prepared via {app.route} "
                 f"({'automatic' if decision.automatic else 'needs approval'})", actor=actor,
                 entity=("application", app.id), details={"reasons": app.pause_reasons})
    return app


def approval_blockers(app: Application, version: ResumeVersion | None, decision: Decision, route_ready: str | None) -> list[str]:
    """What must be fixed before you can approve (as opposed to warnings you may accept)."""
    blockers = [f"answer the question: {a.question}" for a in app.answers if a.needs_user]
    if version is None or not version.valid:
        blockers.append("the resume has not passed validation")
    if app.route != "manual" and route_ready:
        blockers.append(route_ready)
    blockers += [r for r in decision.manual_reasons if r.startswith(("emergency stop", "you already applied", "the job has expired"))]
    return blockers


def is_due(app: Application, policy) -> bool:  # noqa: ANN001
    """An automatic application may go out now: its review hold has passed and a send window is open."""
    return app.scheduled_for is not None and aware(app.scheduled_for) <= utcnow() and in_window(utcnow(), policy)


async def hold(db: AsyncSession, app: Application, note: str | None = None) -> None:
    """Stop an automatic application before it goes out; it returns to the approval queue."""
    job = app.job
    if job.status != JobStatus.READY_TO_APPLY or app.approved_at is not None or app.mode != ApplicationMode.AUTOMATIC.value:
        raise ServiceError("bad_state", "only a scheduled automatic application can be held", 409)
    app.mode, app.scheduled_for = ApplicationMode.SUPERVISED.value, None
    await transition(db, job, JobStatus.AWAITING_APPROVAL, reason=note or "held by you before it went out", actor="user")
    db.add(ApprovalRequest(user_id=app.user_id, kind="application", job_id=job.id, target_id=app.id,
                           reasons=["held by you before the automatic submission"]))
    await record(db, app.user_id, "application.held", f"automatic application {app.id} held", actor="user",
                 entity=("application", app.id))


async def set_answer(db: AsyncSession, app: Application, answer_id: int, value: str) -> None:
    row = next((a for a in app.answers if a.id == answer_id), None)
    if row is None:
        raise ServiceError("not_found", "answer not found", 404)
    if app.outcome != Outcome.PENDING:
        raise ServiceError("already_submitted", "answers cannot change after submission", 409)
    row.answer, row.source, row.needs_user = value.strip()[:5000], "user", not value.strip()
    await record(db, app.user_id, "application.answer", f"answer provided for '{row.question[:80]}'", actor="user",
                 entity=("application", app.id))


async def approve(db: AsyncSession, rt: Runtime, app: Application, note: str | None = None) -> None:
    job = app.job
    if job.status != JobStatus.AWAITING_APPROVAL:
        raise ServiceError("bad_state", f"the job is '{job.status}', not awaiting approval", 409)
    version = await db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    decision = await decision_for(db, rt, job, app)
    if blockers := approval_blockers(app, version, decision, route_for(rt, app.route).ready()):
        raise ServiceError("cannot_approve", "; ".join(blockers), 409)
    request = await db.scalar(select(ApprovalRequest).where(
        ApprovalRequest.kind == "application", ApprovalRequest.target_id == app.id, ApprovalRequest.status == "pending"))
    if request is not None:
        request.status, request.decided_at, request.decision_note = "approved", utcnow(), note
    app.approved_at, app.approved_by = utcnow(), "user"
    await transition(db, job, JobStatus.READY_TO_APPLY, reason="approved by you", actor="user")
    await record(db, app.user_id, "application.approved", f"application {app.id} approved", actor="user",
                 entity=("application", app.id), details={"warnings_accepted": decision.manual_reasons})


async def reject(db: AsyncSession, app: Application, note: str | None = None) -> None:
    request = await db.scalar(select(ApprovalRequest).where(
        ApprovalRequest.kind == "application", ApprovalRequest.target_id == app.id, ApprovalRequest.status == "pending"))
    if request is not None:
        request.status, request.decided_at, request.decision_note = "rejected", utcnow(), note
    if app.outcome != Outcome.PENDING:
        raise ServiceError("already_submitted", "already submitted; withdraw it from the tracker instead", 409)
    await transition(db, app.job, JobStatus.WITHDRAWN, reason=note or "you declined to apply", actor="user")


def _package(app: Application, job: JobPosting, version: ResumeVersion, name: str, email: str | None,
             signature: str | None = None) -> Package:
    path = version.pdf_path if app.submitted_format == "pdf" else version.docx_path
    sha = version.pdf_sha256 if app.submitted_format == "pdf" else version.docx_sha256
    filename = resume_filename(name, f".{app.submitted_format}")
    note = (f"Dear Hiring Team at {job.company},\n\nPlease find my application for the {job.title} position "
            f"({job.canonical_url}). I have attached my resume for your review and would welcome the opportunity to "
            "discuss how I could contribute to your team.\n\nThank you for your time and consideration.\n\n"
            + plain_text(signature or "\n".join(["Best regards,", name] + ([email] if email else []))))
    return Package(
        idempotency_key=f"application-{app.id}", job_title=job.title, company=job.company, job_url=job.url,
        apply_email=job.apply_email, applicant_name=name, applicant_email=email, cover_note=note,
        resume=Attachment(path=path, filename=filename, sha256=sha),
        answers={a.question: a.answer or "" for a in app.answers}, behavior=(job.flags or {}).get("mock_behavior"),
    )


async def submit(db: AsyncSession, rt: Runtime, app: Application, *, trigger: str) -> Application:
    """Submit once. ``trigger`` is automatic | approved | retry."""
    job = app.job
    state = await get_policy_state(db, job.user_id)
    if state.emergency_stop:
        raise ServiceError("emergency_stop", "emergency stop is engaged; clear it in Automation first", 423)
    if job.status != JobStatus.READY_TO_APPLY:
        raise ServiceError("bad_state", f"the job is '{job.status}', not ready to apply", 409)
    if any(a.status in _ALREADY_SUBMITTED for a in app.attempts) or app.outcome in (Outcome.CONFIRMED, Outcome.UNCERTAIN):
        raise ServiceError("already_submitted", "this application was already submitted", 409)
    if any(a.status in (AttemptStatus.STARTED, AttemptStatus.UNKNOWN) for a in app.attempts):
        raise ServiceError("verify_first", "an earlier attempt has an unknown result; verify it first", 409)
    if len(app.attempts) >= MAX_ATTEMPTS:
        raise ServiceError("too_many_attempts", f"stopped after {MAX_ATTEMPTS} attempts; apply manually", 409)
    if trigger == "automatic":
        decision = await decision_for(db, rt, job, app)
        if not decision.automatic:
            await transition(db, job, JobStatus.AWAITING_APPROVAL, reason=(decision.manual_reasons or decision.auto_blockers)[0])
            db.add(ApprovalRequest(user_id=job.user_id, kind="application", job_id=job.id, target_id=app.id,
                                   reasons=decision.manual_reasons + decision.auto_blockers))
            return app
    elif app.approved_at is None and app.mode != ApplicationMode.AUTOMATIC.value:
        raise ServiceError("not_approved", "approve the application first", 409)
    if await previously_applied(db, job):
        raise ServiceError("duplicate", "you already applied to a duplicate of this job", 409)
    # Platform-wide ceiling for every submission, automatic or approved (set by the superadmin).
    cap = int((await platform_config(db, "limits"))["daily_application_cap"])
    if (await applied_counts(db, job.user_id))[0] >= cap:
        raise ServiceError("limit", f"the daily limit of {cap} applications is reached; try again tomorrow", 429)
    version = await db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    if version is None or not version.valid:
        raise ServiceError("invalid_resume", "the resume version is missing or failed validation", 409)

    profile = await get_profile(db, job.user_id)
    content_contact = (version.content or {}).get("contact", {})
    name = profile.full_name or content_contact.get("name") or "Applicant"
    email = str(profile.contact_email) if profile.contact_email else content_contact.get("email")
    contact_links = content_contact.get("links") or []
    signature = _signature(EmailFacts(
        name=name, job_title=job.title, company=job.company, job_url=job.url,
        current_title=next((e.get("title") for e in (version.content or {}).get("experience", [])), None),
        email=email, phone=format_phone(profile.phone or content_contact.get("phone")),
        linkedin=full_url(profile.linkedin_url or next((link for link in contact_links if "linkedin" in link.lower()), None))),
        profile.email_style)
    package = _package(app, job, version, name, email, signature)
    if sha256_file(package.resume.path) != package.resume.sha256:
        raise ServiceError("attachment_changed", "the resume file changed after generation; regenerate it", 409)

    attempt = ApplicationAttempt(application_id=app.id, attempt_no=len(app.attempts) + 1,
                                 idempotency_key=package.idempotency_key, trigger=trigger)
    app.attempts.append(attempt)
    app.submitted_file_path, app.submitted_file_sha256 = package.resume.path, package.resume.sha256
    await transition(db, job, JobStatus.APPLICATION_IN_PROGRESS, reason=f"submitting via {app.route}")
    await record(db, app.user_id, "application.attempt", f"attempt {attempt.attempt_no} for application {app.id} via {app.route}",
                 entity=("application", app.id), details={"trigger": trigger, "resume_sha256": package.resume.sha256})
    await db.commit()  # checkpoint: a crash from here on leaves a STARTED attempt, never a silent resubmit

    route = route_for(rt, app.route)
    try:
        result = await route.submit(package)
    except SubmissionTimeout as exc:
        attempt.status, attempt.error = AttemptStatus.UNKNOWN, str(exc)
        await transition(db, job, JobStatus.NEEDS_MANUAL, reason="submission timed out; verify before retrying")
        await notify_application_result(db, job, app, "uncertain", reason=str(exc))
    except NeedsPerson as exc:
        attempt.status, attempt.error = AttemptStatus.FAILED_PERMANENT, str(exc)
        await transition(db, job, JobStatus.NEEDS_MANUAL, reason=str(exc))
        await notify_approval_needed(db, job, [str(exc)])
    except RouteError as exc:
        attempt.status = AttemptStatus.FAILED_RETRYABLE if exc.retryable else AttemptStatus.FAILED_PERMANENT
        attempt.error = str(exc)
        await transition(db, job, JobStatus.APPLICATION_FAILED, reason=str(exc))
        if not exc.retryable or attempt.attempt_no >= MAX_ATTEMPTS:
            app.outcome = Outcome.FAILED
        await notify_application_result(db, job, app, "failed", reason=str(exc))
    else:
        await _record_success(db, job, app, attempt, result, rt.settings.artifacts_dir / "users" / str(app.user_id) / "application_records")
    attempt.finished_at = utcnow()
    await db.commit()
    return app


async def _record_success(db: AsyncSession, job: JobPosting, app: Application, attempt: ApplicationAttempt,
                          result: Submission, records_dir: Path) -> None:
    attempt.status = AttemptStatus.SUCCEEDED if result.outcome == Outcome.CONFIRMED else AttemptStatus.UNCERTAIN
    attempt.response = result.evidence
    attempt.finished_at = utcnow()
    app.outcome = result.outcome
    app.confirmation_ref = result.reference
    app.evidence = result.evidence
    app.submitted_at = utcnow()
    for answer in app.answers:  # keep what was sent, but not sensitive values
        if answer.sensitive and answer.answer:
            answer.answer = "[provided; not retained]"
    await transition(db, job, JobStatus.APPLIED, reason=f"{result.outcome}: {result.reference or 'no reference'}")
    await record(db, app.user_id, "application.submitted", f"application {app.id} submitted ({result.outcome})",
                 entity=("application", app.id), details={"reference": result.reference, "sha256": app.submitted_file_sha256})
    _write_record(records_dir, job, app)
    await notify_application_result(db, job, app, "submitted" if result.outcome == Outcome.CONFIRMED else "uncertain")


def _write_record(records_dir: Path, job: JobPosting, app: Application) -> None:
    """A plain JSON copy of what was submitted, next to the resumes. Sensitive answers are not included."""
    folder = records_dir / slug(job.company)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"application-{app.id}.json").write_text(json.dumps({
        "application_id": app.id, "job_id": job.id, "title": job.title, "company": job.company, "job_url": job.url,
        "route": app.route, "mode": app.mode, "outcome": app.outcome, "confirmation_ref": app.confirmation_ref,
        "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        "resume_file": app.submitted_file_path, "resume_sha256": app.submitted_file_sha256, "evidence": app.evidence,
        "answers": [{"question": a.question, "answer": None if a.sensitive else a.answer} for a in app.answers],
        "attempts": [{"no": t.attempt_no, "status": t.status, "trigger": t.trigger, "error": t.error} for t in app.attempts],
    }, indent=2, default=str))


async def verify_unknown(db: AsyncSession, rt: Runtime, app: Application) -> str:
    """Resolve an UNKNOWN attempt by asking the route. Returns what happened."""
    attempt = next((a for a in reversed(app.attempts) if a.status in (AttemptStatus.UNKNOWN, AttemptStatus.STARTED)), None)
    if attempt is None:
        raise ServiceError("nothing_to_verify", "no attempt with an unknown result", 409)
    result = await route_for(rt, app.route).verify(attempt.idempotency_key)
    job = app.job
    if result is None:
        return "cannot_verify"  # stays needs-manual: check with the employer, then confirm or retry
    if result.outcome == Outcome.FAILED:
        attempt.status, attempt.finished_at = AttemptStatus.FAILED_RETRYABLE, utcnow()
        attempt.error = "verified: the submission did not arrive"
        if job.status == JobStatus.NEEDS_MANUAL:
            await transition(db, job, JobStatus.APPLICATION_FAILED, reason="verified not received; safe to retry")
        return "not_received"
    if job.status == JobStatus.APPLICATION_IN_PROGRESS:
        await transition(db, job, JobStatus.NEEDS_MANUAL, reason="recovering")
    await _record_success(db, job, app, attempt, result, rt.settings.artifacts_dir / "users" / str(app.user_id) / "application_records")
    return "received"


async def retry(db: AsyncSession, rt: Runtime, app: Application) -> Application:
    job = app.job
    last = app.attempts[-1] if app.attempts else None
    if job.status != JobStatus.APPLICATION_FAILED or last is None or last.status != AttemptStatus.FAILED_RETRYABLE:
        raise ServiceError("not_retryable", "only a failed attempt that is safe to retry can be retried", 409)
    await transition(db, job, JobStatus.READY_TO_APPLY, reason="retrying", actor="user")
    return await submit(db, rt, app, trigger="retry")


async def confirm_manual(db: AsyncSession, rt: Runtime, app: Application, reference: str | None,
                         note: str | None, *, confirmation_page: str | None = None, channel: str = "manual") -> None:
    """You applied on the employer's site (yourself, or with the browser extension). Recorded as
    confirmed only with a reference or the employer's own confirmation page text; otherwise uncertain."""
    job = app.job
    if app.outcome in (Outcome.CONFIRMED, Outcome.UNCERTAIN):
        raise ServiceError("already_submitted", "this application is already recorded as submitted", 409)
    if job.status not in (JobStatus.AWAITING_APPROVAL, JobStatus.READY_TO_APPLY, JobStatus.NEEDS_MANUAL,
                          JobStatus.APPLICATION_FAILED):
        raise ServiceError("bad_state", f"cannot confirm while the job is '{job.status}'", 409)
    version = await db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    if version is not None and app.submitted_file_path is None:
        app.submitted_file_path, app.submitted_file_sha256 = version.pdf_path, version.pdf_sha256
    attempt = ApplicationAttempt(application_id=app.id, attempt_no=len(app.attempts) + 1,
                                 idempotency_key=f"application-{app.id}", trigger="manual")
    app.attempts.append(attempt)
    evidence = {"channel": channel, "note": (note or "")[:500], "reported_by": "you"}
    if confirmation_page:
        evidence["confirmation_page"] = confirmation_page[:300]
    result = Submission(Outcome.CONFIRMED if reference or confirmation_page else Outcome.UNCERTAIN, reference, evidence)
    request = await db.scalar(select(ApprovalRequest).where(
        ApprovalRequest.kind == "application", ApprovalRequest.target_id == app.id, ApprovalRequest.status == "pending"))
    if request is not None:
        request.status, request.decided_at, request.decision_note = "approved", utcnow(), "applied manually"
    app.approved_at = app.approved_at or utcnow()
    await _record_success(db, job, app, attempt, result, rt.settings.artifacts_dir / "users" / str(app.user_id) / "application_records")


async def recover_incomplete(db: AsyncSession) -> int:
    """On startup: attempts left STARTED by a crash become UNKNOWN, and their jobs wait for you."""
    attempts = (await db.scalars(select(ApplicationAttempt).where(ApplicationAttempt.status == AttemptStatus.STARTED))).all()
    for attempt in attempts:
        attempt.status, attempt.error = AttemptStatus.UNKNOWN, "process stopped during submission"
        attempt.finished_at = utcnow()
        app = await db.get(Application, attempt.application_id)
        if app is not None and app.job.status == JobStatus.APPLICATION_IN_PROGRESS:
            await transition(db, app.job, JobStatus.NEEDS_MANUAL,
                             reason="the service stopped during submission; verify before retrying")
            await enqueue(db, app.user_id, "application_uncertain", f"recovery-{attempt.id}",
                          f"Check application: {app.job.title} at {app.job.company}",
                          "The service restarted while this application was being submitted. It was NOT resubmitted.\n"
                          "Open the Application Queue and choose Verify to find out whether it arrived.")
    if attempts:
        await record(db, None, "recovery", f"{len(attempts)} interrupted submission(s) marked for verification", level="warning")
    return len(attempts)

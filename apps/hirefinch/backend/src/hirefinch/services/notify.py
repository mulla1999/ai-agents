"""Builds personal notification messages and queues them in the outbox. Plain text only."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import (
    Application,
    ApprovalRequest,
    AuditEvent,
    EmailDraft,
    JobMatch,
    JobPosting,
    JobStatus,
    NotificationOutbox,
    ResumeVersion,
    utcnow,
)
from ..notifications.email import Attachment
from ..notifications.outbox import enqueue
from ..config import BRAND


async def _score_line(db: AsyncSession, job: JobPosting) -> str:
    match = await db.scalar(select(JobMatch).where(JobMatch.job_id == job.id).order_by(JobMatch.id.desc()).limit(1))
    if match is None:
        return "Match score: not evaluated"
    return f"Match score: {match.score:g}/100 ({match.band}) — {(match.explanation or {}).get('recommendation', '')}"


async def notify_application_result(db: AsyncSession, job: JobPosting, app: Application, kind: str,
                                    *, reason: str | None = None) -> None:
    """kind: submitted | uncertain | failed."""
    attachments: list[Attachment] = []
    if kind in ("submitted", "uncertain") and app.submitted_file_path and app.submitted_file_sha256:
        attachments.append(Attachment(path=app.submitted_file_path, filename=Path(app.submitted_file_path).name,
                                      sha256=app.submitted_file_sha256))
        version = await db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
        other = None
        if version is not None:  # the other format of the same version, labelled as not submitted
            other = (version.docx_path, version.docx_sha256) if app.submitted_format == "pdf" else (version.pdf_path, version.pdf_sha256)
        if other:
            attachments.append(Attachment(path=other[0], filename="not-submitted-copy_" + Path(other[0]).name, sha256=other[1]))
    outreach = await db.scalar(select(EmailDraft.status).where(EmailDraft.job_id == job.id, EmailDraft.kind == "outreach").limit(1))
    headline = {
        "submitted": f"Applied: {job.title} at {job.company}",
        "uncertain": f"Submitted, confirmation pending: {job.title} at {job.company}",
        "failed": f"Application failed: {job.title} at {job.company}",
    }[kind]
    lines = [
        headline, "",
        f"Job: {job.title}", f"Company: {job.company}",
        f"Location: {job.location or 'not stated'} · {job.work_mode or 'work mode not stated'}",
        f"Job URL: {job.url}", await _score_line(db, job), "",
    ]
    if kind == "failed":
        lines += [f"What happened: {reason or 'unknown error'}",
                  "Next step: open the Application Queue to retry or apply manually. Nothing was resubmitted."]
    else:
        lines += [
            f"Submitted at: {app.submitted_at:%Y-%m-%d %H:%M UTC}" if app.submitted_at else "Submitted at: pending",
            f"Method: {app.route} ({'automatic' if app.mode == 'automatic' else 'approved by you'})",
            f"Status: {app.outcome}" + (f" — reference {app.confirmation_ref}" if app.confirmation_ref else ""),
            f"Evidence: {(app.evidence or {}).get('detail') or (app.evidence or {}).get('confirmation_page') or (app.evidence or {}).get('note') or '-'}",
            f"Resume attached: {Path(app.submitted_file_path).name if app.submitted_file_path else '-'} "
            f"(SHA-256 {app.submitted_file_sha256[:12] if app.submitted_file_sha256 else '-'}…), the exact file submitted",
        ]
        if reason:
            lines.append(f"Note: {reason}")
    lines += [f"Recruiter outreach: {outreach or 'none'}", f"Application record: #{app.id} in the Application Tracker"]
    await enqueue(db, job.user_id, {"submitted": "application_submitted", "uncertain": "application_uncertain",
                       "failed": "application_failed"}[kind],
                  f"app-{kind}-{app.id}-{len(app.attempts)}", headline, "\n".join(lines), attachments)


async def notify_approval_needed(db: AsyncSession, job: JobPosting, reasons: list[str]) -> None:
    body = "\n".join([f"{job.title} at {job.company} needs your decision.", f"Job URL: {job.url}",
                      await _score_line(db, job), "", "Why:", *[f"- {r}" for r in reasons[:8]],
                      "", "Open the Application Queue to review the resume and approve or decline."])
    await enqueue(db, job.user_id, "approval_required", f"approval-{job.id}-{utcnow():%Y%m%d}", f"Approval needed: {job.title} at {job.company}", body)


async def notify_auto_scheduled(db: AsyncSession, job: JobPosting, app: Application, timezone: str) -> None:
    from zoneinfo import ZoneInfo

    when = app.scheduled_for.astimezone(ZoneInfo(timezone)) if app.scheduled_for else None
    label = f"{when:%a %d %b, %H:%M}" if when else "soon"
    await enqueue(db, job.user_id, "approval_required", f"auto-scheduled-{app.id}",
                  f"Will apply automatically {label}: {job.title} at {job.company}",
                  f"{job.title} at {job.company} met every automatic-application condition.\n{job.url}\n"
                  f"{await _score_line(db, job)}\n\nIt will be submitted {label} ({timezone}).\n"
                  "To review or stop it, open the Application Queue and choose Hold.")


async def notify_high_priority(db: AsyncSession, job: JobPosting, score: float) -> None:
    await enqueue(db, job.user_id, "high_priority_job", f"high-{job.id}", f"High match ({score:g}): {job.title} at {job.company}",
                  f"{job.title} at {job.company}\n{job.location or ''}\n{job.url}\n\n{await _score_line(db, job)}")


async def notify_resume_ready(db: AsyncSession, job: JobPosting, version: ResumeVersion) -> None:
    await enqueue(db, job.user_id, "resume_ready", f"resume-{version.id}", f"Resume ready for review: {job.title} at {job.company}",
                  f"A tailored resume (v{version.version_no}, {version.role_family}) is ready in Resume Studio.\n"
                  f"Validation: {'passed' if version.valid else 'FAILED'}\n{job.url}")


async def notify_automation_stopped(db: AsyncSession, user_id: int, reason: str) -> None:
    await enqueue(db, user_id, "automation_stopped", f"stopped-{utcnow():%Y%m%d%H%M}", f"{BRAND} automation stopped",
                  f"Automation stopped: {reason}\nNothing further will be submitted or sent until you clear it in Automation.")


async def notify_connector_auth(db: AsyncSession, user_id: int, source_name: str, message: str) -> None:
    await enqueue(db, user_id, "connector_auth_expired", f"auth-{source_name}-{utcnow():%Y%m%d}", f"Reconnect {source_name}",
                  f"{source_name} stopped: {message}\nDiscovery from this source is paused until credentials are fixed.")


async def daily_summary(db: AsyncSession, user_id: int) -> dict:
    since = utcnow() - timedelta(days=1)

    async def count(model, *where) -> int:  # noqa: ANN001
        return int(await db.scalar(select(func.count()).select_from(model).where(model.user_id == user_id, *where)) or 0)

    return {
        "discovered": await count(JobPosting, JobPosting.discovered_at >= since),
        "qualified": await count(JobMatch, JobMatch.created_at >= since, JobMatch.band.in_(("high", "good"))),
        "applications": await count(Application, Application.submitted_at >= since),
        "outreach_sent": await count(EmailDraft, EmailDraft.status == "sent", EmailDraft.updated_at >= since),
        "pending_approvals": await count(ApprovalRequest, ApprovalRequest.status == "pending"),
        "interviews": await count(JobPosting, JobPosting.status == JobStatus.INTERVIEW_SCHEDULED),
        "errors": await count(AuditEvent, AuditEvent.at >= since, AuditEvent.level == "error"),
        "dead_notifications": await count(NotificationOutbox, NotificationOutbox.status == "dead"),
    }


async def enqueue_daily_summary(db: AsyncSession, user_id: int, day_label: str) -> NotificationOutbox | None:
    s = await daily_summary(db, user_id)
    body = "\n".join([
        f"Job search summary for {day_label}", "",
        f"Jobs discovered: {s['discovered']}", f"Qualified (good or high match): {s['qualified']}",
        f"Applications submitted: {s['applications']}", f"Recruiter emails sent: {s['outreach_sent']}",
        f"Pending approvals: {s['pending_approvals']}", f"Interviews scheduled: {s['interviews']}",
        f"Errors: {s['errors']}", f"Undeliverable notifications: {s['dead_notifications']}",
    ])
    return await enqueue(db, user_id, "daily_summary", f"digest-{day_label}", f"Job search summary — {day_label}", body)

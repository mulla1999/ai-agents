"""Dashboard metrics, activity/audit log and the notification outbox."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select

from ..errors import ServiceError
from ..db import (
    Application,
    ApprovalRequest,
    AuditEvent,
    EmailDraft,
    JobMatch,
    JobPosting,
    JobSource,
    JobStatus,
    NotificationOutbox,
    Outcome,
    utcnow,
)
from ..notifications.outbox import process_outbox
from ..services.notify import daily_summary, enqueue_daily_summary
from ..services.resumes import active_master
from ..services.settings_store import get_policy_state, get_profile
from .deps import DB, URT, CurrentUser, audit_out, outbox_out

router = APIRouter(prefix="/api", tags=["dashboard"])

FUNNEL = (
    ("discovered", None),
    ("evaluated", None),
    ("shortlisted", (JobStatus.SHORTLISTED, JobStatus.RESUME_PENDING, JobStatus.RESUME_READY, JobStatus.AWAITING_APPROVAL,
                     JobStatus.READY_TO_APPLY, JobStatus.APPLICATION_IN_PROGRESS, JobStatus.APPLIED,
                     JobStatus.RECRUITER_CONTACTED, JobStatus.INTERVIEW_SCHEDULED, JobStatus.REJECTED,
                     JobStatus.APPLICATION_FAILED, JobStatus.NEEDS_MANUAL)),
    ("applied", (JobStatus.APPLIED, JobStatus.RECRUITER_CONTACTED, JobStatus.INTERVIEW_SCHEDULED, JobStatus.REJECTED)),
    ("interview", (JobStatus.INTERVIEW_SCHEDULED,)),
)


@router.get("/dashboard")
async def dashboard(db: DB, rt: URT) -> dict:
    uid = rt.user_id
    now = utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async def count(*where) -> int:  # noqa: ANN002
        return int(await db.scalar(select(func.count(JobPosting.id)).where(JobPosting.user_id == uid, *where)) or 0)

    latest = select(JobMatch.job_id, func.max(JobMatch.id).label("mid")).group_by(JobMatch.job_id).subquery()
    high = int(await db.scalar(select(func.count()).select_from(JobMatch).join(latest, latest.c.mid == JobMatch.id)
                               .where(JobMatch.user_id == uid, JobMatch.band == "high")) or 0)
    funnel = {
        "discovered": await count(JobPosting.is_duplicate.is_(False)),
        "evaluated": await count(JobPosting.status != JobStatus.DISCOVERED, JobPosting.is_duplicate.is_(False)),
    }
    for name, states in FUNNEL[2:]:
        funnel[name] = await count(JobPosting.status.in_(states))
    trend = []
    for back in range(13, -1, -1):
        start = today - timedelta(days=back)
        end = start + timedelta(days=1)
        trend.append({
            "date": start.date().isoformat(),
            "discovered": await count(JobPosting.discovered_at >= start, JobPosting.discovered_at < end),
            "applied": int(await db.scalar(select(func.count(Application.id)).where(Application.user_id == uid,
                Application.submitted_at >= start, Application.submitted_at < end)) or 0),
        })
    recent = (await db.scalars(select(AuditEvent).where(AuditEvent.user_id == uid).order_by(AuditEvent.id.desc()).limit(15))).all()
    warnings: list[dict] = []
    state = await get_policy_state(db, uid)
    if state.emergency_stop:
        warnings.append({"level": "error", "message": f"Emergency stop engaged: {state.stop_reason or ''}"})
    if state.paused:
        warnings.append({"level": "warning", "message": "Automation is paused"})
    if await active_master(db, uid) is None:
        warnings.append({"level": "warning", "message": "No master resume yet: upload one in Profile"})
    if (await get_profile(db, uid)).notification_email is None:
        warnings.append({"level": "info", "message": "No notification email set: notifications are held"})
    if not rt.sender.configured:
        warnings.append({"level": "warning", "message": "Email is not set up: add your SMTP or Gmail in Integrations"})
    elif not rt.sender.delivers:
        warnings.append({"level": "info", "message": "Email provider is the local mailbox: nothing is sent"})
    for source in (await db.scalars(select(JobSource).where(JobSource.user_id == uid, JobSource.enabled.is_(True),
                                                            or_(JobSource.auth_ok.is_(False), JobSource.last_status == "failed")))).all():
        warnings.append({"level": "error", "message": f"{source.name}: {source.last_error or source.last_status}"})
    failed = int(await db.scalar(select(func.count(Application.id)).where(Application.user_id == uid,
                                                                          Application.outcome == Outcome.FAILED)) or 0)
    dead = int(await db.scalar(select(func.count(NotificationOutbox.id)).where(NotificationOutbox.user_id == uid,
                                                                               NotificationOutbox.status == "dead")) or 0)
    return {
        "metrics": {
            "discovered_today": await count(JobPosting.discovered_at >= today),
            "high_match": high,
            "awaiting_resume_review": await count(JobPosting.status == JobStatus.RESUME_READY),
            "applications_submitted": int(await db.scalar(select(func.count(Application.id)).where(Application.user_id == uid,
                Application.outcome.in_((Outcome.CONFIRMED, Outcome.UNCERTAIN)))) or 0),
            "recruiters_contacted": int(await db.scalar(select(func.count(EmailDraft.id)).where(
                EmailDraft.user_id == uid, EmailDraft.status == "sent")) or 0),
            "pending_approvals": int(await db.scalar(select(func.count(ApprovalRequest.id)).where(ApprovalRequest.user_id == uid,
                ApprovalRequest.status == "pending")) or 0),
            "interviews": await count(JobPosting.status == JobStatus.INTERVIEW_SCHEDULED),
            "needs_attention": await count(JobPosting.status.in_((JobStatus.NEEDS_MANUAL, JobStatus.APPLICATION_FAILED))),
            "failed_applications": failed,
            "dead_notifications": dead,
        },
        "funnel": funnel, "trend": trend, "summary": await daily_summary(db, uid),
        "recent_activity": [audit_out(e) for e in recent], "warnings": warnings,
        "mode": state.policy.mode, "paused": state.paused, "emergency_stop": state.emergency_stop,
    }


@router.get("/audit")
async def audit(db: DB, user: CurrentUser, q: str | None = None, level: str | None = None, action: str | None = None,
                entity_type: str | None = None, entity_id: int | None = None,
                page: int = Query(1, ge=1), page_size: int = Query(100, le=500)) -> dict:
    query = select(AuditEvent).where(AuditEvent.user_id == user.id)
    if q:
        query = query.where(func.lower(AuditEvent.message).like(f"%{q.lower()}%"))
    if level:
        query = query.where(AuditEvent.level == level)
    if action:
        query = query.where(AuditEvent.action.like(f"{action}%"))
    if entity_type:
        query = query.where(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(AuditEvent.entity_id == entity_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return {"total": total, "items": [audit_out(e) for e in rows]}


@router.get("/notifications")
async def notifications(db: DB, user: CurrentUser) -> list[dict]:
    rows = (await db.scalars(select(NotificationOutbox).where(NotificationOutbox.user_id == user.id)
                             .order_by(NotificationOutbox.id.desc()).limit(200))).all()
    return [outbox_out(n) for n in rows]


@router.post("/notifications/process")
async def process(request: Request, rt: URT) -> dict:
    if not await request.app.state.runtime.limiter.hit(f"outbox-now:{rt.user_id}", 10, 3600):
        raise ServiceError("rate_limited", "notifications are also sent automatically every few minutes; try again later", 429)
    return await process_outbox(rt.sessionmaker, rt.sender, rt.user_id)


@router.post("/notifications/digest")
async def digest(db: DB, user: CurrentUser) -> dict:
    row = await enqueue_daily_summary(db, user.id, utcnow().strftime("%Y-%m-%d"))
    await db.commit()
    return {"queued": row is not None}

"""FastAPI dependencies and JSON serialisers shared by the routers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import (
    AppUser,
    Application,
    ApprovalRequest,
    AuditEvent,
    EmailDraft,
    JobMatch,
    JobPosting,
    NotificationOutbox,
    RecruiterContact,
    ResumeMaster,
    ResumeVersion,
    Role,
)
from ..errors import ServiceError
from ..runtime import Runtime, UserRuntime


SESSION_COOKIE = "job_agent_session"  # pre-rename cookie names are kept so nobody is signed out


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.runtime.sessionmaker() as session:
        yield session


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


DB = Annotated[AsyncSession, Depends(get_db)]
RT = Annotated[Runtime, Depends(get_runtime)]


async def current_user(request: Request, db: DB) -> AppUser:
    from ..services.accounts import user_for_session

    user = await user_for_session(db, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise ServiceError("unauthenticated", "sign in required", 401)
    return user


CurrentUser = Annotated[AppUser, Depends(current_user)]


async def user_runtime(user: CurrentUser, db: DB, rt: RT) -> UserRuntime:
    return await rt.for_user(db, user.id)


URT = Annotated[UserRuntime, Depends(user_runtime)]


def _require(*roles: str):  # noqa: ANN202
    async def dependency(user: CurrentUser) -> AppUser:
        if user.role not in roles:
            raise ServiceError("forbidden", "administrator access required", 403)
        return user

    return dependency


AdminUser = Annotated[AppUser, Depends(_require(Role.ADMIN, Role.SUPERADMIN))]
SuperAdmin = Annotated[AppUser, Depends(_require(Role.SUPERADMIN))]


async def get_or_404(db: AsyncSession, model: type, ident: int, label: str) -> Any:
    row = await db.get(model, ident)
    if row is None:
        raise ServiceError("not_found", f"{label} not found", 404)
    return row


async def get_owned(db: AsyncSession, model: type, ident: int, user: AppUser, label: str) -> Any:
    """Fetch a row the user owns. Someone else's row is reported as not found (never 403), so ids
    cannot be probed across accounts."""
    row = await db.get(model, ident)
    if row is None or getattr(row, "user_id", None) != user.id:
        raise ServiceError("not_found", f"{label} not found", 404)
    return row


def user_out(user: AppUser) -> dict[str, Any]:
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role, "status": user.status,
            "email_verified": user.email_verified_at is not None, "created_at": iso(user.created_at),
            "two_factor": user.totp_enabled_at is not None, "google_linked": user.google_sub is not None,
            "recovery_codes_left": len(user.recovery_codes or []),
            "last_login_at": iso(user.last_login_at)}


def iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def job_summary(job: JobPosting, match: JobMatch | None) -> dict[str, Any]:
    return {
        "id": job.id, "title": job.title, "company": job.company, "location": job.location, "work_mode": job.work_mode,
        "source": job.source.key if job.source else None, "url": job.url, "status": job.status,
        "status_reason": job.status_reason, "liveness": job.liveness, "posted_at": iso(job.posted_at),
        "discovered_at": iso(job.discovered_at), "salary_text": job.salary_text, "salary_min_lpa": job.salary_min_lpa,
        "salary_max_lpa": job.salary_max_lpa, "experience_min": job.experience_min, "experience_max": job.experience_max,
        "apply_method": job.apply_method, "duplicate_of_id": job.duplicate_of_id,
        "flags": {k: v for k, v in (job.flags or {}).items() if k != "injection_snippets"},
        "score": match.score if match else None, "band": match.band if match else None,
        "confidence": match.confidence if match else None,
    }


def match_out(match: JobMatch | None) -> dict[str, Any] | None:
    if match is None:
        return None
    return {"id": match.id, "score": match.score, "band": match.band, "confidence": match.confidence,
            "recommended": match.recommended, "breakdown": match.breakdown, "explanation": match.explanation,
            "disqualifiers": match.disqualifiers, "scorer_version": match.scorer_version, "created_at": iso(match.created_at)}


def version_out(v: ResumeVersion, *, full: bool = False) -> dict[str, Any]:
    out = {"id": v.id, "job_id": v.job_id, "version_no": v.version_no, "role_family": v.role_family,
           "template_version": v.template_version, "valid": v.valid, "created_at": iso(v.created_at),
           "docx_name": Path(v.docx_path).name, "pdf_name": Path(v.pdf_path).name,
           "docx_sha256": v.docx_sha256, "pdf_sha256": v.pdf_sha256,
           "validation": {k: v.validation.get(k) for k in ("passed", "errors", "warnings")}}
    if full:
        out.update({"content": v.content, "report": v.report, "validation": v.validation})
    return out


def master_out(m: ResumeMaster, *, full: bool = False) -> dict[str, Any]:
    doc = m.corrected or m.parsed
    out = {"id": m.id, "filename": m.filename, "format": m.file_format, "sha256": m.sha256, "is_active": m.is_active,
           "uploaded_at": iso(m.uploaded_at), "corrected": m.corrected is not None,
           "warnings": (m.parsed or {}).get("warnings", []),
           "experience_count": len(doc.get("experience", [])), "skills_count": sum(len(g.get("items", [])) for g in doc.get("skills", []))}
    if full:
        out["document"] = doc
    return out


def application_out(app: Application) -> dict[str, Any]:
    return {
        "id": app.id, "job_id": app.job_id, "job_title": app.job.title, "company": app.job.company,
        "job_status": app.job.status, "status_reason": app.job.status_reason, "route": app.route, "mode": app.mode,
        "outcome": app.outcome, "resume_version_id": app.resume_version_id, "submitted_format": app.submitted_format,
        "submitted_file": Path(app.submitted_file_path).name if app.submitted_file_path else None,
        "submitted_file_sha256": app.submitted_file_sha256, "submitted_at": iso(app.submitted_at),
        "confirmation_ref": app.confirmation_ref, "evidence": app.evidence, "approved_at": iso(app.approved_at),
        "scheduled_for": iso(app.scheduled_for), "pause_reasons": app.pause_reasons, "created_at": iso(app.created_at), "job_url": app.job.url,
        "apply_url": app.job.apply_url, "apply_email": app.job.apply_email,
        "answers": [{"id": a.id, "question": a.question, "category": a.category,
                     "answer": ("••••" if a.sensitive and a.answer and a.source != "user" else a.answer),
                     "source": a.source, "sensitive": a.sensitive, "needs_user": a.needs_user} for a in app.answers],
        "attempts": [{"attempt_no": t.attempt_no, "status": t.status, "trigger": t.trigger, "error": t.error,
                      "started_at": iso(t.started_at), "finished_at": iso(t.finished_at)} for t in app.attempts],
    }


def draft_out(d: EmailDraft) -> dict[str, Any]:
    return {"id": d.id, "job_id": d.job_id, "to": d.to_email, "subject": d.subject, "body": d.body, "status": d.status,
            "resume_version_id": d.resume_version_id, "attachment_format": d.attachment_format,
            "attachment_source": d.attachment_source, "scheduled_for": iso(d.scheduled_for),
            "follow_up_status": d.follow_up_status, "created_at": iso(d.created_at), "updated_at": iso(d.updated_at),
            "deliveries": [{"provider": x.provider, "status": x.status, "message_id": x.message_id, "error": x.error,
                            "attachment_sha256": x.attachment_sha256, "at": iso(x.attempted_at)} for x in d.deliveries]}


def contact_out(c: RecruiterContact) -> dict[str, Any]:
    return {"id": c.id, "job_id": c.job_id, "name": c.name, "title": c.title, "email": c.email, "source": c.source,
            "verified": c.verified, "verification_note": c.verification_note}


def approval_out(a: ApprovalRequest) -> dict[str, Any]:
    return {"id": a.id, "kind": a.kind, "job_id": a.job_id, "target_id": a.target_id, "status": a.status,
            "reasons": a.reasons, "created_at": iso(a.created_at), "decided_at": iso(a.decided_at)}


def audit_out(e: AuditEvent) -> dict[str, Any]:
    return {"id": e.id, "at": iso(e.at), "actor": e.actor, "action": e.action, "level": e.level,
            "entity_type": e.entity_type, "entity_id": e.entity_id, "message": e.message, "details": e.details}


def outbox_out(n: NotificationOutbox) -> dict[str, Any]:
    return {"id": n.id, "kind": n.kind, "subject": n.subject, "status": n.status, "attempts": n.attempts,
            "last_error": n.last_error, "created_at": iso(n.created_at), "sent_at": iso(n.sent_at),
            "attachments": [a.get("filename") for a in n.attachments or []]}

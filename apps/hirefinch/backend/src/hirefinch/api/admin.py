"""Administration. Admins manage accounts; only the superadmin changes roles, deletes accounts and
edits platform settings. Admin views show account metadata and counts, never users' resumes,
jobs, emails or secrets, and the admin audit log shows only account, platform and scheduler events.
"""

from __future__ import annotations

import shutil
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, EmailStr, Field, StringConstraints
from sqlalchemy import func, or_, select

from ..db import (
    Application,
    AppUser,
    AuditEvent,
    JobPosting,
    ResumeMaster,
    Role,
    ScheduledTask,
    UserSession,
    UserStatus,
    utcnow,
)
from ..errors import ServiceError
from ..notifications.email import OutgoingEmail, message_id_for
from ..services import accounts
from ..services import integrations as integ
from ..services.audit import record
from .deps import DB, RT, AdminUser, SuperAdmin, audit_out, iso, user_out
from ..config import BRAND

router = APIRouter(prefix="/api/admin", tags=["admin"])

PLATFORM_ACTIONS = ("account.", "platform.", "scheduler.", "recovery", "admin.")


async def _counts(db, model, user_ids: list[int]) -> dict[int, int]:  # noqa: ANN001
    rows = (await db.execute(select(model.user_id, func.count()).where(model.user_id.in_(user_ids))
                             .group_by(model.user_id))).all()
    return {uid: n for uid, n in rows}


@router.get("/overview")
async def overview(db: DB, _: AdminUser) -> dict:
    by_status = dict((await db.execute(select(AppUser.status, func.count()).group_by(AppUser.status))).all())
    sessions = await db.scalar(select(func.count(UserSession.id)).where(UserSession.expires_at > utcnow()))
    tasks = (await db.scalars(select(ScheduledTask).order_by(ScheduledTask.key))).all()
    return {
        "users": {"total": sum(by_status.values()), **by_status},
        "active_sessions": sessions or 0,
        "jobs": await db.scalar(select(func.count(JobPosting.id))) or 0,
        "applications": await db.scalar(select(func.count(Application.id)).where(Application.submitted_at.is_not(None))) or 0,
        "system_email_configured": await integ.platform_get(db, "system_email") is not None,
        "registration": await integ.platform_config(db, "registration"),
        "limits": await integ.platform_config(db, "limits"),
        "tasks": [{"key": t.key, "interval_minutes": t.interval_minutes, "enabled": t.enabled,
                   "next_run_at": iso(t.next_run_at), "last_run_at": iso(t.last_run_at), "last_status": t.last_status,
                   "last_error": t.last_error} for t in tasks],
    }


@router.get("/users")
async def list_users(db: DB, _: AdminUser, q: str | None = None, status: str | None = None, role: str | None = None,
                     page: int = Query(1, ge=1), page_size: int = Query(50, le=200)) -> dict:
    query = select(AppUser)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(func.lower(AppUser.email).like(like), func.lower(AppUser.full_name).like(like)))
    if status:
        query = query.where(AppUser.status == status)
    if role:
        query = query.where(AppUser.role == role)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    users = (await db.scalars(query.order_by(AppUser.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    ids = [u.id for u in users]
    jobs, apps, resumes = (await _counts(db, JobPosting, ids), await _counts(db, Application, ids),
                           await _counts(db, ResumeMaster, ids))
    return {"total": total, "items": [{**user_out(u), "jobs": jobs.get(u.id, 0), "applications": apps.get(u.id, 0),
                                       "resumes": resumes.get(u.id, 0)} for u in users]}


async def _target(db, actor: AppUser, user_id: int) -> AppUser:  # noqa: ANN001
    target = await db.get(AppUser, user_id)
    if target is None:
        raise ServiceError("not_found", "user not found", 404)
    if target.id == actor.id:
        raise ServiceError("forbidden", "you cannot change your own account here", 403)
    if target.role == Role.SUPERADMIN or (target.role == Role.ADMIN and actor.role != Role.SUPERADMIN):
        raise ServiceError("forbidden", "only the superadmin can change administrator accounts", 403)
    return target


class StatusBody(BaseModel):
    status: str = Field(pattern="^(active|disabled)$")


@router.post("/users/{user_id}/status")
async def set_status(user_id: int, body: StatusBody, db: DB, actor: AdminUser) -> dict:
    target = await _target(db, actor, user_id)
    target.status = UserStatus(body.status)
    if body.status == UserStatus.ACTIVE and target.email_verified_at is None:
        target.email_verified_at = utcnow()  # an admin vouching for the account
    if body.status == UserStatus.DISABLED:
        await accounts.end_all_sessions(db, target.id)
    await record(db, target.id, "admin.status", f"account {body.status} by {actor.email}", actor="user")
    await db.commit()
    return user_out(target)


class RoleBody(BaseModel):
    role: str = Field(pattern="^(admin|user)$")


@router.post("/users/{user_id}/role")
async def set_role(user_id: int, body: RoleBody, db: DB, actor: SuperAdmin) -> dict:
    target = await _target(db, actor, user_id)
    target.role = Role(body.role)
    await record(db, target.id, "admin.role", f"role set to {body.role} by {actor.email}", actor="user")
    await db.commit()
    return user_out(target)


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, db: DB, rt: RT, actor: SuperAdmin) -> dict:
    target = await _target(db, actor, user_id)
    await accounts.delete_account(db, target)
    await record(db, None, "admin.delete", f"account {user_id} deleted by {actor.email}", actor="user")
    await db.commit()
    for folder in (rt.settings.data_dir / "masters" / str(user_id), rt.settings.artifacts_dir / "users" / str(user_id),
                   rt.settings.data_dir / "mailbox" / str(user_id)):
        shutil.rmtree(folder, ignore_errors=True)
    return {"deleted": True}


# ---------------------------------------------------------------- platform settings (superadmin)


@router.get("/settings")
async def get_settings(db: DB, rt: RT, _: SuperAdmin) -> dict:
    return {
        "registration": await integ.platform_config(db, "registration"),
        "limits": await integ.platform_config(db, "limits"),
        "system_email": integ.public_view(await integ.platform_get(db, "system_email"), "system_email", rt.box),
        "retention": await integ.platform_config(db, "retention"),
        "google_oauth": {**integ.public_view(await integ.platform_get(db, "google_oauth"), "google_oauth", rt.box),
                         "redirect_uri": f"{rt.settings.public_url.rstrip('/')}/api/auth/google/callback"},
    }


class PlatformBody(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict, max_length=30)
    secrets: dict[str, Annotated[str, StringConstraints(max_length=4096)] | None] = Field(default_factory=dict, max_length=5)


@router.put("/settings/{key}")
async def put_settings(key: str, body: PlatformBody, db: DB, rt: RT, actor: SuperAdmin) -> dict:
    await integ.platform_save(db, rt.settings, rt.box, key, body.config, body.secrets, actor.id)
    await db.commit()
    return await get_settings(db, rt, actor)


class TestEmailBody(BaseModel):
    to: EmailStr


@router.post("/settings/system_email/test")
async def test_system_email(body: TestEmailBody, db: DB, rt: RT, _: SuperAdmin) -> dict:
    sender = await integ.system_sender(db, rt.settings, rt.http, rt.box)
    if not sender.configured:
        return {"ok": False, "message": "set up the platform email first"}
    try:
        result = await sender.send(OutgoingEmail(to=str(body.to), subject=f"{BRAND} platform email test",
                                                 body="The platform email works: verification and reset emails can be sent.",
                                                 message_id=message_id_for(f"system-test-{utcnow():%Y%m%d%H%M%S}")))
    except Exception as exc:
        return {"ok": False, "message": str(exc)[:300]}
    return {"ok": True, "message": result.detail}


class TaskBody(BaseModel):
    interval_minutes: int = Field(ge=1, le=10080)
    enabled: bool


@router.put("/tasks/{key}")
async def put_task(key: str, body: TaskBody, db: DB, actor: SuperAdmin) -> dict:
    task = await db.scalar(select(ScheduledTask).where(ScheduledTask.key == key))
    if task is None:
        raise ServiceError("not_found", "task not found", 404)
    task.interval_minutes, task.enabled = body.interval_minutes, body.enabled
    await record(db, None, "platform.task", f"task {key}: every {body.interval_minutes} min, enabled={body.enabled}",
                 actor="user")
    await db.commit()
    return await overview(db, actor)


@router.get("/audit")
async def platform_audit(db: DB, _: AdminUser, q: str | None = None, level: str | None = None,
                         page: int = Query(1, ge=1), page_size: int = Query(100, le=500)) -> dict:
    query = select(AuditEvent).where(or_(*(AuditEvent.action.like(f"{p}%") for p in PLATFORM_ACTIONS)))
    if q:
        query = query.where(func.lower(AuditEvent.message).like(f"%{q.lower()}%"))
    if level:
        query = query.where(AuditEvent.level == level)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    emails = dict((await db.execute(select(AppUser.id, AppUser.email).where(
        AppUser.id.in_({r.user_id for r in rows if r.user_id})))).all())
    return {"total": total, "items": [{**audit_out(r), "user_email": emails.get(r.user_id)} for r in rows]}

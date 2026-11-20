"""Admin: scheme data management, users and roles, stats."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from ..auth.deps import DB, AdminUser
from ..db import Application, ChatMessage, Citizen, Role, SchemeRecord, SchemeRevision, User, UserSession, utcnow
from ..errors import BadRequest, NotFound
from ..schemes import Scheme
from ..services import schemes as scheme_service
from ..services.access import audit
from .schemas import SchemeOut, SchemeRevisionOut, StatsOut, UserOut, UserUpdateIn

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- schemes --------------------------------------------------------------------------------


@router.get("/schemes")
async def list_all_schemes(_: AdminUser, db: DB) -> list[SchemeOut]:
    return [SchemeOut.of(r) for r in await db.scalars(select(SchemeRecord).order_by(SchemeRecord.name))]


@router.get("/schemes/{scheme_id}")
async def get_scheme(scheme_id: str, _: AdminUser, db: DB) -> SchemeOut:
    return SchemeOut.of(await scheme_service.get_record(db, scheme_id))


@router.post("/schemes", status_code=201)
async def create_scheme(body: Scheme, request: Request, user: AdminUser, db: DB) -> SchemeOut:
    record = await scheme_service.create_scheme(db, body, user)
    audit(db, user, "scheme.create", "scheme", record.id)
    await db.commit()
    request.app.state.scheme_source.invalidate()
    return SchemeOut.of(record)


@router.put("/schemes/{scheme_id}")
async def update_scheme(scheme_id: str, body: Scheme, request: Request, user: AdminUser, db: DB) -> SchemeOut:
    if body.id != scheme_id:
        raise BadRequest("the scheme id cannot be changed")
    record = await scheme_service.get_record(db, scheme_id)
    if "applies_to" not in body.model_fields_set:  # older clients: keep the stored setting
        body = body.model_copy(update={"applies_to": record.applies_to})
    await scheme_service.update_scheme(db, record, body, user)
    audit(db, user, "scheme.update", "scheme", record.id, {"version": record.version})
    await db.commit()
    request.app.state.scheme_source.invalidate()
    return SchemeOut.of(record)


@router.post("/schemes/{scheme_id}/verify")
async def verify_scheme(scheme_id: str, request: Request, user: AdminUser, db: DB) -> SchemeOut:
    record = await scheme_service.get_record(db, scheme_id)
    scheme_service.verify_scheme(record, user)
    audit(db, user, "scheme.verify", "scheme", record.id, {"version": record.version})
    await db.commit()
    request.app.state.scheme_source.invalidate()
    return SchemeOut.of(record)


@router.post("/schemes/{scheme_id}/archive")
async def archive_scheme(scheme_id: str, request: Request, user: AdminUser, db: DB) -> SchemeOut:
    record = await scheme_service.get_record(db, scheme_id)
    scheme_service.archive_scheme(record, user)
    audit(db, user, "scheme.archive", "scheme", record.id)
    await db.commit()
    request.app.state.scheme_source.invalidate()
    return SchemeOut.of(record)


@router.get("/schemes/{scheme_id}/revisions")
async def scheme_revisions(scheme_id: str, _: AdminUser, db: DB) -> list[SchemeRevisionOut]:
    await scheme_service.get_record(db, scheme_id)
    rows = await db.scalars(
        select(SchemeRevision).where(SchemeRevision.scheme_id == scheme_id).order_by(SchemeRevision.version.desc())
    )
    return [SchemeRevisionOut.model_validate(r) for r in rows]


# --- users ----------------------------------------------------------------------------------


@router.get("/users")
async def list_users(
    _: AdminUser,
    db: DB,
    role: Role | None = None,
    q: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[UserOut]:
    query = select(User)
    if role is not None:
        query = query.where(User.role == role)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(
            User.email.ilike(pattern, escape="\\")
            | User.display_name.ilike(pattern, escape="\\")
            | User.phone_e164.like(pattern, escape="\\")
        )
    rows = await db.scalars(query.order_by(User.created_at.desc()).limit(limit).offset(offset))
    return [UserOut.of(u) for u in rows]


@router.patch("/users/{user_id}")
async def update_user(user_id: uuid.UUID, body: UserUpdateIn, admin: AdminUser, db: DB) -> UserOut:
    if user_id == admin.id and (body.role not in (None, Role.ADMIN) or body.is_active is False):
        raise HTTPException(status_code=400, detail="you cannot remove your own admin access")
    user = await db.get(User, user_id)
    if user is None:
        raise NotFound("user not found")
    changes: dict[str, str] = {}
    if body.role is not None and body.role is not user.role:
        changes["role"] = f"{user.role}->{body.role}"
        user.role = body.role
    if body.is_active is not None and body.is_active != user.is_active:
        changes["is_active"] = str(body.is_active)
        user.is_active = body.is_active
        if not body.is_active:  # sign the user out everywhere
            for session in await db.scalars(select(UserSession).where(UserSession.user_id == user.id)):
                await db.delete(session)
    if body.display_name is not None:
        user.display_name = body.display_name.strip() or None
    if changes:
        audit(db, admin, "user.update", "user", user.id, changes)
    await db.commit()
    return UserOut.of(user)


# --- stats ----------------------------------------------------------------------------------


@router.get("/stats")
async def stats(_: AdminUser, db: DB) -> StatsOut:
    async def grouped(column) -> dict[str, int]:
        rows = (await db.execute(select(column, func.count()).group_by(column))).all()
        return {str(key): count for key, count in rows}

    return StatsOut(
        users_by_role=await grouped(User.role),
        citizens=await db.scalar(select(func.count()).select_from(Citizen)) or 0,
        citizens_with_consent=await db.scalar(
            select(func.count()).select_from(Citizen).where(Citizen.consent_at.is_not(None))
        )
        or 0,
        applications_by_status=await grouped(Application.status),
        schemes_by_status=await grouped(SchemeRecord.status),
        chat_messages_last_7_days=await db.scalar(
            select(func.count()).select_from(ChatMessage).where(ChatMessage.created_at >= utcnow() - timedelta(days=7))
        )
        or 0,
    )

"""Citizen records: self-service and helper-managed."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from ..auth.deps import DB, AppSettings, CurrentUser, StaffUser
from ..auth.sessions import clear_session_cookie
from ..db import Application, ChatMessage, Citizen, Conversation, Role, User, utcnow
from ..profile import UserProfile, field_descriptors
from ..schemes import Status, evaluate_all
from ..services.access import audit, load_citizen, require_consent
from ..services.citizens import CitizenDetails, apply_details, effective_profile
from ..services.conversations import profile_to_json
from .schemas import CitizenCreateIn, CitizenOut, MatchOut, ProfileFieldOut

router = APIRouter(prefix="/api", tags=["citizens"])

_STATUS_ORDER = {Status.ELIGIBLE: 0, Status.NEEDS_INFO: 1, Status.NOT_ELIGIBLE: 2}


@router.get("/profile-fields")
async def profile_fields() -> list[ProfileFieldOut]:
    return [ProfileFieldOut(**d) for d in field_descriptors()]


@router.get("/me/citizen")
async def my_citizen(user: CurrentUser, db: DB) -> CitizenOut:
    citizen = await db.scalar(select(Citizen).where(Citizen.user_id == user.id))
    if citizen is None:
        citizen = Citizen(user_id=user.id, display_name=user.display_name or "Me")
        db.add(citizen)
        await db.commit()
    return CitizenOut.of(citizen, user)


@router.delete("/me", status_code=204)
async def delete_my_account(user: CurrentUser, db: DB, settings: AppSettings) -> Response:
    """Erase the signed-in user, their own citizen record and everything linked to it."""
    citizen_ids = (await db.scalars(select(Citizen.id).where(Citizen.user_id == user.id))).all()
    await _erase_citizens(db, citizen_ids)
    audit(db, None, "user.self_delete", "user", user.id)
    # Bulk delete: the database cascades to identities and sessions (and nulls staff references).
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response


@router.get("/citizens")
async def list_citizens(
    user: StaffUser,
    db: DB,
    q: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[CitizenOut]:
    query = select(Citizen).where(Citizen.user_id.is_(None) | (Citizen.user_id != user.id))
    if user.role is Role.HELPER:
        query = query.where(Citizen.managed_by_user_id == user.id)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Citizen.display_name.ilike(f"%{escaped}%", escape="\\"))
    rows = (await db.scalars(query.order_by(Citizen.updated_at.desc()).limit(limit).offset(offset))).all()
    return [CitizenOut.of(c, user) for c in rows]


@router.post("/citizens", status_code=201)
async def create_citizen(body: CitizenCreateIn, user: StaffUser, db: DB) -> CitizenOut:
    citizen = Citizen(display_name=body.display_name.strip(), language=body.language, managed_by_user_id=user.id)
    db.add(citizen)
    await db.flush()
    audit(db, user, "citizen.create", "citizen", citizen.id)
    await db.commit()
    return CitizenOut.of(citizen, user)


@router.get("/citizens/{citizen_id}")
async def get_citizen(citizen_id: uuid.UUID, user: CurrentUser, db: DB) -> CitizenOut:
    citizen = await load_citizen(db, user, citizen_id, action="view")
    await db.commit()
    return CitizenOut.of(citizen, user)


@router.delete("/citizens/{citizen_id}", status_code=204)
async def erase_citizen(citizen_id: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    citizen = await load_citizen(db, user, citizen_id, action="erase")
    audit(db, user, "citizen.erase", "citizen", citizen.id)
    await _erase_citizens(db, [citizen.id])
    await db.commit()
    return Response(status_code=204)


@router.put("/citizens/{citizen_id}/profile")
async def update_profile(citizen_id: uuid.UUID, body: UserProfile, user: CurrentUser, db: DB) -> CitizenOut:
    citizen = await load_citizen(db, user, citizen_id, action="edit_profile")
    require_consent(citizen)
    citizen.profile = profile_to_json(body)
    await db.commit()
    return CitizenOut.of(citizen, user)


@router.put("/citizens/{citizen_id}/details")
async def update_details(citizen_id: uuid.UUID, body: CitizenDetails, user: CurrentUser, db: DB) -> CitizenOut:
    citizen = await load_citizen(db, user, citizen_id, action="edit_details")
    require_consent(citizen)
    apply_details(citizen, body)
    await db.commit()
    return CitizenOut.of(citizen, user)


@router.post("/citizens/{citizen_id}/consent")
async def give_consent(citizen_id: uuid.UUID, user: CurrentUser, db: DB, settings: AppSettings) -> CitizenOut:
    citizen = await load_citizen(db, user, citizen_id, action="consent")
    citizen.consent_version = settings.consent_version
    citizen.consent_at = utcnow()
    await db.commit()
    return CitizenOut.of(citizen, user)


@router.get("/citizens/{citizen_id}/eligibility")
async def eligibility(citizen_id: uuid.UUID, request: Request, user: CurrentUser, db: DB) -> list[MatchOut]:
    citizen = await load_citizen(db, user, citizen_id, action="eligibility")
    await db.commit()
    schemes = await request.app.state.scheme_source.active()
    matches = evaluate_all(schemes, effective_profile(citizen))
    matches.sort(key=lambda m: (_STATUS_ORDER[m.status], m.scheme.name))
    return [MatchOut.of(m) for m in matches]


@router.get("/citizens/{citizen_id}/export")
async def export_citizen(citizen_id: uuid.UUID, user: CurrentUser, db: DB) -> dict[str, Any]:
    """Everything stored about one citizen, for the right to access."""
    citizen = await load_citizen(db, user, citizen_id, action="export")
    applications = (
        await db.scalars(
            select(Application).where(Application.citizen_id == citizen.id).options(selectinload(Application.events))
        )
    ).all()
    messages = (
        await db.execute(
            select(Conversation.channel, ChatMessage.role, ChatMessage.content, ChatMessage.created_at)
            .join(ChatMessage, ChatMessage.conversation_id == Conversation.id)
            .where(Conversation.citizen_id == citizen.id)
            .order_by(ChatMessage.created_at)
        )
    ).all()
    await db.commit()
    return {
        "citizen": CitizenOut.of(citizen, user).model_dump(mode="json"),  # includes contact and address details
        "applications": [
            {
                "scheme_id": a.scheme_id,
                "status": a.status.value,
                "portal_reference": a.portal_reference,
                "checklist": a.checklist,
                "notes": a.notes,
                "history": [
                    {"from": e.from_status, "to": e.to_status, "note": e.note, "at": e.created_at.isoformat()}
                    for e in a.events
                ],
            }
            for a in applications
        ],
        "messages": [
            {"channel": str(m.channel), "role": m.role, "content": m.content, "at": m.created_at.isoformat()}
            for m in messages
        ],
    }


async def _erase_citizens(db: DB, citizen_ids: Sequence[uuid.UUID]) -> None:
    # The database cascades to conversations, messages, applications and their events.
    if citizen_ids:
        await db.execute(delete(Citizen).where(Citizen.id.in_(list(citizen_ids))))


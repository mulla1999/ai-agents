"""Tracking a citizen's applications and their status history."""

from __future__ import annotations

import re

from agents_core.privacy import redact_pii
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Application, ApplicationEvent, ApplicationStatus, Citizen, SchemeRecord, SchemeStatus, User
from ..errors import BadRequest, Conflict

S = ApplicationStatus
TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    S.INTERESTED: frozenset({S.DOCUMENTS_READY, S.SUBMITTED, S.WITHDRAWN}),
    S.DOCUMENTS_READY: frozenset({S.INTERESTED, S.SUBMITTED, S.WITHDRAWN}),
    S.SUBMITTED: frozenset({S.APPROVED, S.REJECTED, S.WITHDRAWN}),
    S.APPROVED: frozenset({S.BENEFIT_RECEIVED}),
    S.REJECTED: frozenset({S.INTERESTED}),
    S.BENEFIT_RECEIVED: frozenset(),
    S.WITHDRAWN: frozenset({S.INTERESTED}),
}

_AADHAAR_LIKE = re.compile(r"^\s*[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\s*$")


async def create_application(db: AsyncSession, citizen: Citizen, scheme: SchemeRecord, actor: User) -> Application:
    if scheme.status is SchemeStatus.ARCHIVED:
        raise BadRequest("this scheme is no longer active")
    existing = await db.scalar(
        select(Application.id).where(Application.citizen_id == citizen.id, Application.scheme_id == scheme.id)
    )
    if existing is not None:
        raise Conflict("an application for this scheme is already being tracked")
    application = Application(
        citizen_id=citizen.id,
        scheme_id=scheme.id,
        status=S.INTERESTED,
        checklist={doc: False for doc in scheme.documents},
        created_by_user_id=actor.id,
    )
    application.events = [ApplicationEvent(from_status=None, to_status=S.INTERESTED, actor_user_id=actor.id)]
    db.add(application)
    return application


def update_application(
    application: Application,
    actor: User,
    *,
    status: ApplicationStatus | None = None,
    checklist: dict[str, bool] | None = None,
    portal_reference: str | None = None,
    notes: str | None = None,
    note: str | None = None,
) -> None:
    if checklist is not None:
        unknown = set(checklist) - set(application.checklist)
        if unknown:
            raise BadRequest(f"unknown checklist items: {sorted(unknown)}")
        application.checklist = {**application.checklist, **checklist}
    if portal_reference is not None:
        if _AADHAAR_LIKE.match(portal_reference):
            raise BadRequest("this looks like an Aadhaar number; enter the portal's application number instead")
        application.portal_reference = portal_reference.strip() or None
    if notes is not None:
        application.notes = redact_pii(notes).strip() or None
    if status is not None and status is not application.status:
        if status not in TRANSITIONS[application.status]:
            raise BadRequest(f"cannot move an application from {application.status} to {status}")
        application.events.append(
            ApplicationEvent(
                from_status=application.status,
                to_status=status,
                note=redact_pii(note) if note else None,
                actor_user_id=actor.id,
            )
        )
        application.status = status

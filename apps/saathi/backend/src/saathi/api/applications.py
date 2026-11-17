"""Application tracking for a citizen."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..auth.deps import DB, CurrentUser
from ..db import Application, SchemeRecord
from ..errors import NotFound
from ..services.access import audit, load_citizen, require_consent
from ..services.applications import create_application, update_application
from ..services.schemes import get_record
from .schemas import ApplicationCreateIn, ApplicationOut, ApplicationUpdateIn

router = APIRouter(prefix="/api", tags=["applications"])


@router.get("/citizens/{citizen_id}/applications")
async def list_applications(citizen_id: uuid.UUID, user: CurrentUser, db: DB) -> list[ApplicationOut]:
    citizen = await load_citizen(db, user, citizen_id, action="list_applications")
    rows = (
        await db.execute(
            select(Application, SchemeRecord)
            .join(SchemeRecord, Application.scheme_id == SchemeRecord.id)
            .where(Application.citizen_id == citizen.id)
            .options(selectinload(Application.events))
            .order_by(Application.updated_at.desc())
        )
    ).all()
    await db.commit()
    return [ApplicationOut.of(app, scheme) for app, scheme in rows]


@router.post("/citizens/{citizen_id}/applications", status_code=201)
async def start_application(
    citizen_id: uuid.UUID, body: ApplicationCreateIn, user: CurrentUser, db: DB
) -> ApplicationOut:
    citizen = await load_citizen(db, user, citizen_id, action="create_application")
    require_consent(citizen)
    scheme = await get_record(db, body.scheme_id)
    application = await create_application(db, citizen, scheme, user)
    await db.commit()
    return ApplicationOut.of(application, scheme)


@router.patch("/applications/{application_id}")
async def change_application(
    application_id: uuid.UUID, body: ApplicationUpdateIn, user: CurrentUser, db: DB
) -> ApplicationOut:
    application = await db.scalar(
        select(Application).where(Application.id == application_id).options(selectinload(Application.events))
    )
    if application is None:
        raise NotFound("application not found")
    await load_citizen(db, user, application.citizen_id, action="update_application")  # access check
    update_application(
        application,
        user,
        status=body.status,
        checklist=body.checklist,
        portal_reference=body.portal_reference,
        notes=body.notes,
        note=body.note,
    )
    if body.status is not None:
        audit(db, user, "application.status", "application", application.id, {"to": body.status.value})
    await db.commit()
    scheme = await get_record(db, application.scheme_id)
    return ApplicationOut.of(application, scheme)

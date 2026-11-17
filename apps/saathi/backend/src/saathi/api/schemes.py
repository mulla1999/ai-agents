"""Public, read-only scheme catalogue."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from ..auth.deps import DB
from ..db import SchemeRecord, SchemeStatus
from ..errors import NotFound
from .schemas import SchemeOut

router = APIRouter(prefix="/api/schemes", tags=["schemes"])


@router.get("")
async def list_schemes(db: DB) -> list[SchemeOut]:
    rows = await db.scalars(
        select(SchemeRecord).where(SchemeRecord.status != SchemeStatus.ARCHIVED).order_by(SchemeRecord.name)
    )
    return [SchemeOut.of(r) for r in rows]


@router.get("/{scheme_id}")
async def get_scheme(scheme_id: str, db: DB) -> SchemeOut:
    record = await db.get(SchemeRecord, scheme_id)
    if record is None or record.status is SchemeStatus.ARCHIVED:
        raise NotFound("scheme not found")
    return SchemeOut.of(record)

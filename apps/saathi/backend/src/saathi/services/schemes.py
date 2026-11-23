"""Scheme data in the database: conversion, the agent's scheme source, edits and verification."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db import SchemeRecord, SchemeRevision, SchemeStatus, User
from ..errors import Conflict, NotFound
from ..schemes import Scheme, load_schemes

log = logging.getLogger(__name__)

_SCHEME_COLUMNS = (
    "name", "level", "state", "applies_to", "ministry", "tags", "summary", "benefits", "eligibility",
    "documents", "notes", "how_to_apply", "apply_url", "source_url",
)  # fmt: skip


def record_to_scheme(record: SchemeRecord) -> Scheme:
    data = {column: getattr(record, column) for column in _SCHEME_COLUMNS}
    verified_on = record.verified_on if record.status is SchemeStatus.VERIFIED else None
    return Scheme.model_validate({"id": record.id, **data, "verified_on": verified_on})


def _apply_scheme(record: SchemeRecord, scheme: Scheme) -> None:
    data = scheme.model_dump(mode="json")
    for column in _SCHEME_COLUMNS:
        setattr(record, column, data[column])


class DbSchemeSource:
    """Active schemes for the agent and eligibility API, cached briefly; edits call ``invalidate``."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], *, include_drafts: bool, ttl: float = 60):
        self._sessionmaker = sessionmaker
        self._statuses = [SchemeStatus.VERIFIED, SchemeStatus.DRAFT] if include_drafts else [SchemeStatus.VERIFIED]
        self._ttl = ttl
        self._cache: list[Scheme] = []
        self._expires = 0.0

    async def active(self) -> Sequence[Scheme]:
        if time.monotonic() < self._expires:
            return self._cache
        async with self._sessionmaker() as db:
            records = (
                await db.scalars(
                    select(SchemeRecord).where(SchemeRecord.status.in_(self._statuses)).order_by(SchemeRecord.name)
                )
            ).all()
        schemes = []
        for record in records:
            try:
                schemes.append(record_to_scheme(record))
            except ValidationError:
                log.error("scheme %s in the database is invalid; skipping it", record.id)
        self._cache, self._expires = schemes, time.monotonic() + self._ttl
        return schemes

    def invalidate(self) -> None:
        self._expires = 0.0


async def get_record(db: AsyncSession, scheme_id: str) -> SchemeRecord:
    record = await db.get(SchemeRecord, scheme_id)
    if record is None:
        raise NotFound("scheme not found")
    return record


async def create_scheme(db: AsyncSession, scheme: Scheme, actor: User | None) -> SchemeRecord:
    if await db.get(SchemeRecord, scheme.id) is not None:
        raise Conflict(f"scheme {scheme.id!r} already exists")
    record = SchemeRecord(id=scheme.id, version=1, status=SchemeStatus.DRAFT, updated_by_user_id=actor and actor.id)
    _apply_scheme(record, scheme)
    db.add(record)
    db.add(_revision(record, scheme, actor))
    return record


async def update_scheme(db: AsyncSession, record: SchemeRecord, scheme: Scheme, actor: User) -> SchemeRecord:
    """Any edit needs a fresh review, so the scheme goes back to draft."""
    _apply_scheme(record, scheme)
    record.version += 1
    record.status = SchemeStatus.DRAFT
    record.verified_on = None
    record.verified_by_user_id = None
    record.updated_by_user_id = actor.id
    db.add(_revision(record, scheme, actor))
    return record


def verify_scheme(record: SchemeRecord, actor: User) -> None:
    record.status = SchemeStatus.VERIFIED
    record.verified_on = date.today()
    record.verified_by_user_id = actor.id


def archive_scheme(record: SchemeRecord, actor: User) -> None:
    record.status = SchemeStatus.ARCHIVED
    record.updated_by_user_id = actor.id


def _revision(record: SchemeRecord, scheme: Scheme, actor: User | None) -> SchemeRevision:
    return SchemeRevision(
        scheme_id=record.id,
        version=record.version,
        data=scheme.model_dump(mode="json"),
        changed_by_user_id=actor.id if actor else None,
    )


async def sync_schemes(db: AsyncSession, directory: Path, *, apply: bool) -> list[tuple[str, str]]:
    """Bring the database in line with the YAML files, for corrections made after a database was seeded.

    Returns (scheme id, action) for every record that differs: "add", "update" or "skip (archived)".
    With ``apply`` the changes are made like an admin edit (version + 1, a revision row, so earlier
    versions can be restored); the status follows the file (verified with its date, or draft).
    Records that exist only in the database, and archived ones, are left alone.
    """
    changes: list[tuple[str, str]] = []
    for scheme in load_schemes(directory):
        record = await db.get(SchemeRecord, scheme.id)
        if record is None:
            changes.append((scheme.id, "add"))
            if apply:
                record = await create_scheme(db, scheme, None)
                _set_status_from_file(record, scheme)
            continue
        wanted = scheme.model_dump(mode="json")
        current = {column: getattr(record, column) for column in _SCHEME_COLUMNS}
        status_differs = (record.status is SchemeStatus.VERIFIED) != (scheme.verified_on is not None) or (
            scheme.verified_on is not None and record.verified_on != scheme.verified_on
        )
        if all(current[c] == wanted[c] for c in _SCHEME_COLUMNS) and not status_differs:
            continue
        if record.status is SchemeStatus.ARCHIVED:
            changes.append((scheme.id, "skip (archived)"))
            continue
        changes.append((scheme.id, "update"))
        if apply:
            _apply_scheme(record, scheme)
            record.version += 1
            record.updated_by_user_id = None
            _set_status_from_file(record, scheme)
            db.add(_revision(record, scheme, None))
    if apply:
        await db.commit()
    return changes


def _set_status_from_file(record: SchemeRecord, scheme: Scheme) -> None:
    record.status = SchemeStatus.VERIFIED if scheme.verified_on else SchemeStatus.DRAFT
    record.verified_on = scheme.verified_on
    record.verified_by_user_id = None


async def seed_schemes(db: AsyncSession, directory: Path) -> int:
    """Insert YAML schemes that are not in the database yet. Existing records are never overwritten."""
    added = 0
    for scheme in load_schemes(directory):
        if await db.get(SchemeRecord, scheme.id) is not None:
            continue
        record = await create_scheme(db, scheme, None)
        if scheme.verified_on is not None:
            record.status = SchemeStatus.VERIFIED
            record.verified_on = scheme.verified_on
        added += 1
    await db.commit()
    return added

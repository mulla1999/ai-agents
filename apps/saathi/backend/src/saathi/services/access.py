"""Who may see which citizen record, and the audit trail of staff access."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import AuditLog, Citizen, Role, User
from ..errors import BadRequest, NotFound


def can_access(user: User, citizen: Citizen) -> bool:
    if user.role is Role.ADMIN or citizen.user_id == user.id:
        return True
    return user.role is Role.HELPER and citizen.managed_by_user_id == user.id


async def load_citizen(db: AsyncSession, user: User, citizen_id: uuid.UUID, *, action: str) -> Citizen:
    """Return the citizen if ``user`` may access it. Otherwise 404, so IDs cannot be probed."""
    citizen = await db.get(Citizen, citizen_id)
    if citizen is None or not can_access(user, citizen):
        raise NotFound("citizen not found")
    if citizen.user_id != user.id:
        audit(db, user, f"citizen.{action}", "citizen", citizen.id)
    return citizen


def require_consent(citizen: Citizen) -> None:
    """No personal data is collected for a citizen until consent is recorded."""
    if citizen.consent_at is None:
        raise BadRequest("consent_required")


def audit(
    db: AsyncSession,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: Any,
    details: dict[str, Any] | None = None,
) -> None:
    """Record who did what to which record. ``details`` must never contain profile contents or PII."""
    db.add(
        AuditLog(
            actor_user_id=actor.id if actor else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            details=details or {},
        )
    )

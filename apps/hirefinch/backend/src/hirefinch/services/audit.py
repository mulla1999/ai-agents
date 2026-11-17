"""Audit trail. Messages and details must never contain secrets or whole documents."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import AuditEvent

log = logging.getLogger("hirefinch.audit")


async def record(
    db: AsyncSession,
    user_id: int | None,  # owner of the event; None for platform events
    action: str,
    message: str,
    *,
    actor: str = "system",
    level: str = "info",
    entity: tuple[str, int | None] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            user_id=user_id,
            actor=actor,
            action=action,
            level=level,
            entity_type=entity[0] if entity else None,
            entity_id=entity[1] if entity else None,
            message=message[:1000],
            details=details or {},
        )
    )
    log.log(logging.WARNING if level != "info" else logging.INFO, "%s %s", action, message[:200])

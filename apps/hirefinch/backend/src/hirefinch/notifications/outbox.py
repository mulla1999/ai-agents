"""Personal notifications through a persistent outbox.

Events enqueue a message with a dedupe key, so the same event never produces two emails. A worker
sends due messages with exponential backoff; after ``MAX_ATTEMPTS`` a message is marked dead and
shown on the dashboard. A failed notification never re-runs the action it reports on.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db import NotificationOutbox, utcnow
from ..services.audit import record
from ..services.settings_store import get_policy_state, get_profile
from .email import Attachment, EmailError, EmailSender, OutgoingEmail, message_id_for

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 6


async def enqueue(db: AsyncSession, user_id: int, kind: str, dedupe_key: str, subject: str, body: str,
                  attachments: list[Attachment] | None = None) -> NotificationOutbox | None:
    policy = (await get_policy_state(db, user_id)).policy
    if kind not in policy.notify:
        return None
    mine = (NotificationOutbox.user_id == user_id, NotificationOutbox.dedupe_key == dedupe_key[:200])
    existing = await db.scalar(select(NotificationOutbox).where(*mine))
    if existing is not None:
        return existing
    row = NotificationOutbox(user_id=user_id, kind=kind, dedupe_key=dedupe_key[:200], subject=subject[:300], body=body,
                             attachments=[a.__dict__ for a in attachments or []])
    try:
        async with db.begin_nested():
            db.add(row)
    except IntegrityError:  # raced with another enqueue of the same event
        return await db.scalar(select(NotificationOutbox).where(*mine))
    return row


async def process_outbox(sessionmaker: async_sessionmaker[AsyncSession], sender: EmailSender, user_id: int, *,
                         limit: int = 20) -> dict:
    """Send one user's due notifications through that user's own email settings."""
    sent = failed = held = 0
    async with sessionmaker() as db:
        to = (await get_profile(db, user_id)).notification_email
        state = await get_policy_state(db, user_id)
        rows = (await db.scalars(
            select(NotificationOutbox)
            .where(NotificationOutbox.user_id == user_id, NotificationOutbox.status.in_(("pending", "held")),
                   NotificationOutbox.next_attempt_at <= utcnow())
            .order_by(NotificationOutbox.id).limit(limit)
        )).all()
        for row in rows:
            reason = None
            if not to:
                reason = "set a notification email in Profile to receive notifications"
            elif not sender.configured:
                reason = getattr(sender, "reason", "set up email in Settings → Integrations")
            elif state.emergency_stop and row.kind != "automation_stopped":
                reason = "emergency stop is engaged"
            if reason:  # waits without using up retries
                row.status, row.last_error = "held", reason
                held += 1
                continue
            mail = OutgoingEmail(to=str(to), subject=row.subject, body=row.body,
                                 message_id=message_id_for(f"notify-u{user_id}-{row.id}-{row.dedupe_key}"),
                                 attachments=[Attachment(**a) for a in row.attachments or []])
            row.attempts += 1
            try:
                result = await sender.send(mail)
            except EmailError as exc:
                row.last_error = str(exc)[:1000]
                if not exc.retryable or row.attempts >= MAX_ATTEMPTS:
                    row.status = "dead"
                    await record(db, user_id, "notification.dead", f"notification '{row.subject[:80]}' gave up: {exc}",
                                 level="error", entity=("notification", row.id))
                else:
                    row.status = "pending"
                    row.next_attempt_at = utcnow() + timedelta(minutes=2 ** row.attempts)
                failed += 1
            else:
                row.status, row.sent_at, row.message_id, row.last_error = "sent", utcnow(), result.message_id, None
                sent += 1
            await db.commit()
        await db.commit()
    return {"sent": sent, "failed": failed, "held": held}

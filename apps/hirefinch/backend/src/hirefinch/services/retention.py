"""Data retention for inactive accounts (platform setting ``retention``, superadmin).

* An account with no sign-in for ``inactive_days`` gets a warning email (system email). If nobody
  signs in within ``warn_days`` after that, the account and all its data are deleted.
* Signing in clears the warning. The superadmin is never deleted. ``inactive_days = 0`` turns
  account deletion off.
* Independently, audit events and sent or dead notifications older than their limits are removed.
"""

from __future__ import annotations

import logging
import shutil
from datetime import timedelta

from sqlalchemy import delete, func, select

from ..db import AppUser, AuditEvent, NotificationOutbox, Role, aware, utcnow
from ..notifications.email import EmailError, OutgoingEmail, message_id_for
from .accounts import delete_account
from .audit import record
from .integrations import platform_config, system_sender
from ..config import BRAND

log = logging.getLogger(__name__)


async def run_retention(rt) -> str:  # noqa: ANN001 (process Runtime)
    async with rt.sessionmaker() as db:
        cfg = await platform_config(db, "retention")
        inactive, warn = int(cfg["inactive_days"]), int(cfg["warn_days"])
        now = utcnow()
        warned = deleted = 0
        if inactive > 0:
            sender = await system_sender(db, rt.settings, rt.http, rt.box)
            users = (await db.scalars(select(AppUser).where(AppUser.role != Role.SUPERADMIN))).all()
            for user in users:
                last = aware(user.last_login_at) or aware(user.created_at)
                if last is None or now - last < timedelta(days=inactive):
                    continue
                if user.retention_warned_at is None:
                    if not sender.configured:
                        continue  # never delete without having been able to warn
                    try:
                        await sender.send(OutgoingEmail(
                            to=user.email, subject=f"Your {BRAND} account will be deleted",
                            body=(f"You have not signed in for {inactive} days. Your account and everything in it "
                                  f"(resumes, jobs, applications, settings) will be deleted in {warn} days.\n\n"
                                  f"Sign in at {rt.settings.public_url} to keep it."),
                            message_id=message_id_for(f"retention-{user.id}-{now:%Y%m%d}")))
                    except EmailError as exc:
                        log.warning("retention warning to user %s failed: %s", user.id, exc)
                        continue
                    user.retention_warned_at = now
                    warned += 1
                    await record(db, user.id, "account.retention_warning", f"inactive for {inactive} days; warned")
                elif now - aware(user.retention_warned_at) >= timedelta(days=warn):  # type: ignore[operator]
                    user_id = user.id
                    await delete_account(db, user)
                    await record(db, None, "account.retention_deleted", f"account {user_id} deleted after {inactive} days inactive")
                    for folder in (rt.settings.data_dir / "masters" / str(user_id),
                                   rt.settings.artifacts_dir / "users" / str(user_id),
                                   rt.settings.data_dir / "mailbox" / str(user_id)):
                        shutil.rmtree(folder, ignore_errors=True)
                    deleted += 1
                await db.commit()
        audit_cut = now - timedelta(days=int(cfg["audit_days"]))
        note_cut = now - timedelta(days=int(cfg["notification_days"]))
        old_audit = await db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.at < audit_cut)) or 0
        await db.execute(delete(AuditEvent).where(AuditEvent.at < audit_cut))
        await db.execute(delete(NotificationOutbox).where(NotificationOutbox.status.in_(("sent", "dead")),
                                                          NotificationOutbox.created_at < note_cut))
        await db.commit()
    return f"{warned} warned, {deleted} deleted, {old_audit} old audit events removed"

"""Background scheduler: persistent tasks in ``scheduled_task``, one asyncio loop per process.

Tasks: ``discovery`` (checks which sources are due, then advances the pipeline), ``outbox``
(sends notifications), ``digest`` (daily summary at the configured local hour) and ``reconcile``
(expires jobs past their deadline). Each task runs for every active user in that user's own
runtime. A lease column prevents overlapping runs; each user's pause and emergency stop apply
only to that user.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from .db import AppUser, JobPosting, JobStatus, ScheduledTask, UserStatus, aware, utcnow
from .notifications.outbox import process_outbox
from .runtime import Runtime, UserRuntime
from .services.audit import record
from .services.notify import enqueue_daily_summary
from .services.settings_store import get_policy_state
from .workflow.pipeline import dispatch_due, run_discovery
from .workflow.states import TRANSITIONS, transition

log = logging.getLogger(__name__)

DEFAULT_TASKS = {"discovery": 15, "outbox": 2, "digest": 30, "reconcile": 60, "retention": 1440}
LEASE = timedelta(minutes=30)


async def ensure_tasks(rt: Runtime) -> None:
    async with rt.sessionmaker() as db:
        existing = set((await db.scalars(select(ScheduledTask.key))).all())
        for key, minutes in DEFAULT_TASKS.items():
            if key not in existing:
                db.add(ScheduledTask(key=key, kind=key, interval_minutes=minutes))
        await db.commit()


async def active_user_ids(rt: Runtime) -> list[int]:
    async with rt.sessionmaker() as db:
        return list((await db.scalars(select(AppUser.id).where(AppUser.status == UserStatus.ACTIVE)
                                      .order_by(AppUser.id))).all())


async def _for_each_user(rt: Runtime, job) -> list[str]:  # noqa: ANN001
    """Run ``job(user_runtime)`` for every active user; one user's failure never stops the others."""
    out = []
    for user_id in await active_user_ids(rt):
        async with rt.sessionmaker() as db:
            urt = await rt.for_user(db, user_id)
        try:
            out.append(f"u{user_id}: {await job(urt)}")
        except Exception as exc:
            log.exception("scheduled work failed for user %s", user_id)
            out.append(f"u{user_id}: failed ({exc.__class__.__name__})")
    return out


async def _digest(urt: UserRuntime) -> str:
    async with urt.sessionmaker() as db:
        policy = (await get_policy_state(db, urt.user_id)).policy
        now = datetime.now(ZoneInfo(policy.timezone))
        if now.hour < policy.digest_hour_local:
            return "not yet"
        row = await enqueue_daily_summary(db, urt.user_id, now.strftime("%Y-%m-%d"))
        await db.commit()
        return "queued" if row is not None else "disabled"


async def _discovery(urt: UserRuntime) -> str:
    report = await run_discovery(urt, scheduled=True)
    return f"{report.new_jobs} new, {sum(report.advanced.values())} stages, {len(report.errors)} errors"


async def _outbox(urt: UserRuntime) -> str:
    due = await dispatch_due(urt)  # automatic applications and emails whose time has come
    result = await process_outbox(urt.sessionmaker, urt.sender, urt.user_id)
    return f"{due['applications']} applied, {due['emails']} emailed, {result['sent']} notifications sent"


async def _reconcile(rt: Runtime) -> str:
    today = utcnow().date()
    count = 0
    async with rt.sessionmaker() as db:
        jobs = (await db.scalars(select(JobPosting).where(JobPosting.deadline < today,
                                                          JobPosting.status != JobStatus.EXPIRED))).all()
        for job in jobs:
            if JobStatus.EXPIRED in TRANSITIONS[JobStatus(job.status)]:
                job.liveness = "expired"
                await transition(db, job, JobStatus.EXPIRED, reason="deadline passed")
                count += 1
        await db.commit()
    return f"{count} expired"


async def run_task(rt: Runtime, key: str) -> str:
    per_user = {"discovery": _discovery, "outbox": _outbox, "digest": _digest}
    if key in per_user:
        results = await _for_each_user(rt, per_user[key])
        return "; ".join(results)[:1000] or "no active users"
    if key == "reconcile":
        return await _reconcile(rt)
    if key == "retention":
        from .services.retention import run_retention

        return await run_retention(rt)
    return "unknown task"


async def tick(rt: Runtime) -> list[str]:
    ran: list[str] = []
    now = utcnow()
    async with rt.sessionmaker() as db:
        tasks = (await db.scalars(select(ScheduledTask).where(ScheduledTask.enabled.is_(True)))).all()
        due = [t for t in tasks if aware(t.next_run_at) <= now and (t.lease_until is None or aware(t.lease_until) < now)]
    for task in due:  # each user's pause and emergency stop are honoured inside the per-user work
        async with rt.sessionmaker() as db:
            claimed = await db.execute(
                update(ScheduledTask)
                .where(ScheduledTask.id == task.id, (ScheduledTask.lease_until.is_(None)) | (ScheduledTask.lease_until < now))
                .values(lease_until=now + LEASE)
            )
            await db.commit()
            if claimed.rowcount != 1:  # type: ignore[attr-defined]
                continue
        status, detail = "ok", ""
        try:
            detail = await run_task(rt, task.key)
        except Exception as exc:
            log.exception("scheduled task %s failed", task.key)
            status, detail = "failed", f"{exc.__class__.__name__}: {exc}"[:1000]
        async with rt.sessionmaker() as db:
            row = await db.get(ScheduledTask, task.id)
            if row is not None:
                row.lease_until, row.last_run_at = None, utcnow()
                row.next_run_at = utcnow() + timedelta(minutes=row.interval_minutes)
                row.last_status, row.last_error = status, detail if status != "ok" else None
                if status != "ok":
                    await record(db, None, "scheduler.failed", f"{task.key}: {detail}", actor="scheduler", level="error")
            await db.commit()
        ran.append(f"{task.key}: {detail}")
    return ran


async def run_forever(rt: Runtime, stop: asyncio.Event) -> None:
    await ensure_tasks(rt)
    while not stop.is_set():
        try:
            await tick(rt)
        except Exception:
            log.exception("scheduler tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=rt.settings.scheduler_tick_seconds)
        except TimeoutError:
            pass

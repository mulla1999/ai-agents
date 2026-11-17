"""Job lifecycle state machine. Every status change goes through ``transition`` so it is validated
and audited; nothing else writes ``JobPosting.status``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import JobPosting, JobStatus
from ..services.audit import record

S = JobStatus

# Withdrawn/expired are reachable from every state before an application is under way.
_EXIT_EARLY = {S.WITHDRAWN, S.EXPIRED}

TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    S.DISCOVERED: {S.MATCH_EVALUATED} | _EXIT_EARLY,
    S.MATCH_EVALUATED: {S.MATCH_EVALUATED, S.SHORTLISTED} | _EXIT_EARLY,
    S.SHORTLISTED: {S.RESUME_PENDING, S.MATCH_EVALUATED} | _EXIT_EARLY,
    S.RESUME_PENDING: {S.RESUME_READY, S.NEEDS_MANUAL} | _EXIT_EARLY,
    S.RESUME_READY: {S.AWAITING_APPROVAL, S.READY_TO_APPLY, S.RESUME_PENDING, S.NEEDS_MANUAL} | _EXIT_EARLY,
    # → APPLIED here only via confirm_manual: you applied on the employer's site yourself.
    S.AWAITING_APPROVAL: {S.READY_TO_APPLY, S.RESUME_PENDING, S.NEEDS_MANUAL, S.APPLIED} | _EXIT_EARLY,
    S.READY_TO_APPLY: {S.APPLICATION_IN_PROGRESS, S.AWAITING_APPROVAL, S.RESUME_PENDING, S.NEEDS_MANUAL,
                       S.APPLIED} | _EXIT_EARLY,
    S.APPLICATION_IN_PROGRESS: {S.APPLIED, S.APPLICATION_FAILED, S.NEEDS_MANUAL},
    S.APPLICATION_FAILED: {S.READY_TO_APPLY, S.NEEDS_MANUAL, S.APPLIED} | _EXIT_EARLY,
    # From needs-manual you can confirm you applied yourself, retry, or regenerate.
    S.NEEDS_MANUAL: {S.READY_TO_APPLY, S.AWAITING_APPROVAL, S.RESUME_PENDING, S.APPLIED, S.APPLICATION_FAILED} | _EXIT_EARLY,
    S.APPLIED: {S.RECRUITER_CONTACTED, S.INTERVIEW_SCHEDULED, S.REJECTED, S.WITHDRAWN},
    S.RECRUITER_CONTACTED: {S.INTERVIEW_SCHEDULED, S.REJECTED, S.WITHDRAWN},
    S.INTERVIEW_SCHEDULED: {S.REJECTED, S.WITHDRAWN, S.INTERVIEW_SCHEDULED},
    S.REJECTED: set(),
    S.WITHDRAWN: {S.MATCH_EVALUATED},  # undo a dismissal
    S.EXPIRED: set(),
}

# Statuses meaning an application exists on the employer's side.
SUBMITTED_STATES = frozenset({S.APPLIED, S.RECRUITER_CONTACTED, S.INTERVIEW_SCHEDULED, S.REJECTED})
# Statuses the tracker lets you set by hand.
MANUAL_STATES = frozenset({S.INTERVIEW_SCHEDULED, S.REJECTED, S.WITHDRAWN, S.EXPIRED})


class TransitionError(ValueError):
    pass


def can_transition(current: str, target: str) -> bool:
    return JobStatus(target) in TRANSITIONS[JobStatus(current)]


async def transition(
    db: AsyncSession, job: JobPosting, target: JobStatus, *, reason: str | None = None, actor: str = "system"
) -> None:
    current = JobStatus(job.status)
    if target not in TRANSITIONS[current]:
        raise TransitionError(f"cannot move job {job.id} from {current} to {target}")
    job.status = target
    job.status_reason = (reason or "")[:500] or None
    await record(db, job.user_id, "job.status", f"{current} → {target}" + (f": {reason}" if reason else ""), actor=actor,
                 entity=("job", job.id), details={"from": current, "to": target})

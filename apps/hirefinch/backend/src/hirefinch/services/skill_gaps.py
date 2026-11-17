"""Skills a job asks for that your resume doesn't show, and your answers about them.

Matching lists them as gaps. You can say you have one (with a line on where you used it; it becomes a
verified extra skill, used in matching and in a tailored resume's Skills section) or that you don't
(remembered, so you're not asked again). Saying you have one re-scores every job that listed it.
"""

from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import JobMatch, JobPosting, JobStatus
from ..domain import VerifiedSkill
from ..errors import ServiceError
from ..skills import canonicalize
from .audit import record
from .jobs import evaluate_job, load_candidate
from .settings_store import get_profile, save_profile

_GAP = re.compile(r"^(Required skill not evidenced in your resume|Preferred skill not evidenced): (.+)$")
# Jobs still worth improving a score for (not applied to, rejected or dismissed).
OPEN = (JobStatus.DISCOVERED, JobStatus.MATCH_EVALUATED, JobStatus.SHORTLISTED, JobStatus.RESUME_PENDING,
        JobStatus.RESUME_READY, JobStatus.AWAITING_APPROVAL, JobStatus.READY_TO_APPLY, JobStatus.NEEDS_MANUAL)


def gaps_of(match: JobMatch | None) -> list[tuple[str, bool]]:
    """(skill, required) pairs from a match's explanation."""
    out = []
    for line in ((match.explanation or {}).get("resume_gaps") or []) if match else []:
        if m := _GAP.match(str(line)):
            out.append((m.group(2).strip(), m.group(1).startswith("Required")))
    return out


async def _latest_matches(db: AsyncSession, user_id: int, job_ids: list[int] | None = None) -> list[JobMatch]:
    latest = (select(JobMatch.job_id, func.max(JobMatch.created_at).label("at"))
              .where(JobMatch.user_id == user_id).group_by(JobMatch.job_id).subquery())
    query = (select(JobMatch).join(latest, (JobMatch.job_id == latest.c.job_id) & (JobMatch.created_at == latest.c.at))
             .join(JobPosting, JobPosting.id == JobMatch.job_id)
             .where(JobPosting.user_id == user_id, JobPosting.status.in_(OPEN), JobPosting.is_duplicate.is_(False)))
    if job_ids is not None:
        query = query.where(JobMatch.job_id.in_(job_ids))
    return list((await db.scalars(query)).all())


async def _answered(db: AsyncSession, user_id: int) -> tuple[set[str], set[str]]:
    profile = await get_profile(db, user_id)
    return ({canonicalize(s.name).lower() for s in profile.verified_extra_skills},
            {canonicalize(s).lower() for s in profile.declined_skills})


async def job_gaps(db: AsyncSession, user_id: int, job_id: int) -> list[dict]:
    job = await db.get(JobPosting, job_id)
    if job is None or job.user_id != user_id:
        raise ServiceError("not_found", "job not found", 404)
    match = await db.scalar(select(JobMatch).where(JobMatch.job_id == job_id).order_by(JobMatch.created_at.desc()).limit(1))
    known, declined = await _answered(db, user_id)
    return [{"skill": s, "required": req, "declined": s.lower() in declined}
            for s, req in gaps_of(match) if s.lower() not in known]


async def top_gaps(db: AsyncSession, user_id: int, limit: int = 8) -> list[dict]:
    """Required skills your open jobs most often say you're missing, that you haven't answered about."""
    known, declined = await _answered(db, user_id)
    jobs: dict[str, set[int]] = defaultdict(set)
    for match in await _latest_matches(db, user_id):
        for skill, required in gaps_of(match):
            if required and skill.lower() not in known | declined:
                jobs[skill].add(match.job_id)
    ranked = sorted(jobs.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))[:limit]
    return [{"skill": skill, "jobs": len(ids)} for skill, ids in ranked]


async def answer(db: AsyncSession, user_id: int, skill: str, knows: bool, evidence: str = "") -> dict:
    """Record your answer. "Yes" (with where you used it) re-scores every open job that listed the skill."""
    name = canonicalize(" ".join(skill.split()))[:80]
    if not name:
        raise ServiceError("invalid", "which skill?", 422)
    profile = await get_profile(db, user_id)
    lower = name.lower()
    profile.declined_skills = [s for s in profile.declined_skills if canonicalize(s).lower() != lower]
    if knows:
        evidence = " ".join(evidence.split())
        if len(evidence) < 3:
            raise ServiceError("evidence_required", "add a few words on where you used it", 422)
        if not any(canonicalize(s.name).lower() == lower for s in profile.verified_extra_skills):
            if len(profile.verified_extra_skills) >= 50:
                raise ServiceError("limit", "you can add up to 50 skills that aren't on your resume", 409)
            profile.verified_extra_skills.append(VerifiedSkill(name=name, evidence=evidence[:500]))
    else:
        profile.declined_skills.append(name)
    await save_profile(db, user_id, profile)
    await db.flush()
    rescored = 0
    if knows:
        affected = [m.job_id for m in await _latest_matches(db, user_id) if any(s.lower() == lower for s, _ in gaps_of(m))]
        loaded = await load_candidate(db, user_id)
        if loaded is not None and affected:
            candidate, master_id = loaded
            for job in (await db.scalars(select(JobPosting).where(JobPosting.id.in_(affected)))).all():
                await evaluate_job(db, job, candidate, master_id)
                rescored += 1
    await record(db, user_id, "skills.answered", f"{'has' if knows else 'does not have'} {name}"
                 + (f"; {rescored} jobs re-scored" if rescored else ""), actor="user")
    return {"skill": name, "knows": knows, "rescored": rescored}

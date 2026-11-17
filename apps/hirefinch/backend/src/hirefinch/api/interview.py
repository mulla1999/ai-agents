"""Interview preparation for a job (questions, your STAR stories, questions to ask)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from ..db import InterviewPrep
from ..errors import ServiceError
from ..services import interview_prep as service
from .deps import DB, URT, CurrentUser, iso

router = APIRouter(prefix="/api/jobs", tags=["interview"])


def _out(prep: InterviewPrep | None) -> dict:
    if prep is None:
        return {"prep": None}
    return {"prep": {**prep.content, "used_llm": prep.used_llm, "created_at": iso(prep.created_at)}}


@router.get("/{job_id}/interview-prep")
async def get_prep(job_id: int, db: DB, user: CurrentUser) -> dict:
    return _out(await db.scalar(select(InterviewPrep).where(InterviewPrep.user_id == user.id, InterviewPrep.job_id == job_id)))


@router.post("/{job_id}/interview-prep")
async def make_prep(job_id: int, request: Request, db: DB, rt: URT) -> dict:
    if not await request.app.state.runtime.limiter.hit(f"interview-prep:{rt.user_id}", 20, 3600):
        raise ServiceError("rate_limited", "that's a lot of interview prep in an hour; try again a bit later", 429)
    prep = await service.generate(db, rt.user_id, job_id, rt.llm)
    await db.commit()
    return _out(prep)

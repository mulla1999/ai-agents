"""Skills jobs ask for that your resume doesn't show: what's missing, and your answers."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..errors import ServiceError
from ..services import skill_gaps as service
from .deps import DB, CurrentUser

router = APIRouter(prefix="/api", tags=["skills"])


@router.get("/jobs/{job_id}/skill-gaps")
async def job_gaps(job_id: int, db: DB, user: CurrentUser) -> list[dict]:
    return await service.job_gaps(db, user.id, job_id)


@router.get("/skills/gaps")
async def top_gaps(db: DB, user: CurrentUser) -> list[dict]:
    return await service.top_gaps(db, user.id)


class AnswerBody(BaseModel):
    skill: str = Field(min_length=1, max_length=80)
    knows: bool
    evidence: str = Field(default="", max_length=500)


@router.post("/skills/answer")
async def answer(body: AnswerBody, request: Request, db: DB, user: CurrentUser) -> dict:
    if not await request.app.state.runtime.limiter.hit(f"skill-answer:{user.id}", 60, 3600):
        raise ServiceError("rate_limited", "that's a lot of answers in an hour; try again a bit later", 429)
    result = await service.answer(db, user.id, body.skill, body.knows, body.evidence)
    await db.commit()
    return result

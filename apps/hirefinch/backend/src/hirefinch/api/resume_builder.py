"""Resume Builder: check, preview and save a resume written on the site, with optional AI writing help."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..domain import ResumeDocument
from ..errors import ServiceError
from ..db import JobPosting
from ..domain import ParsedJob
from ..resume import ats_test, skillpacks
from ..resume.coaching import Tip, review
from ..services import resume_builder as builder
from ..services.integrations import platform_config
from .deps import DB, URT, CurrentUser, master_out

router = APIRouter(prefix="/api/resume-builder", tags=["resume-builder"])


async def _limit(request: Request, key: str, n: int, window: int = 3600) -> None:
    if not await request.app.state.runtime.limiter.hit(key, n, window):
        raise ServiceError("rate_limited", "that's a lot of requests in a short time; wait a few minutes and try again", 429)


@router.post("/review")
async def check(document: ResumeDocument, user: CurrentUser) -> dict:
    # A draft over the save limits (e.g. a very long summary) still gets its tips; the limit is one of them.
    try:
        return review(builder.prepare(document)).as_dict()
    except ServiceError as exc:
        report = review(document)
        same = next((t for t in report.tips if t.section in exc.message), None)
        if same is not None:  # already said (e.g. "shorten the summary"): make that tip a must-fix
            same.level = "fix"
            report.tips.sort(key=lambda t: t.level != "fix")
        else:
            report.tips.insert(0, Tip("fix", "limits", exc.message[0].upper() + exc.message[1:] + "."))
        report.score = max(0, report.score - 12)
        return report.as_dict()


@router.post("/preview")
async def preview(document: ResumeDocument, request: Request, user: CurrentUser) -> Response:
    await _limit(request, f"builder-preview:{user.id}", 120)
    pdf = builder.render_pdf(builder.prepare(document))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": "inline", "Cache-Control": "no-store"})


@router.post("/save", status_code=201)
async def save(document: ResumeDocument, request: Request, db: DB, rt: URT) -> dict:
    await _limit(request, f"builder-save:{rt.user_id}", 30)
    limits = await platform_config(db, "limits")
    master = await builder.save(db, rt.settings, rt.user_id, document, max_resumes=int(limits["max_resumes"]))
    await db.commit()
    return master_out(master, full=True)


class BulletBody(BaseModel):
    text: str = Field(max_length=400)
    role: str = Field(default="", max_length=200)
    facts: str = Field(default="", max_length=400)


@router.post("/improve-bullet")
async def improve_bullet(body: BulletBody, request: Request, rt: URT) -> dict:
    await _limit(request, f"builder-ai:{rt.user_id}", 60)
    return await builder.improve_bullet(rt.llm, body.text, body.role, body.facts)


@router.post("/summary")
async def summary(document: ResumeDocument, request: Request, rt: URT) -> dict:
    await _limit(request, f"builder-ai:{rt.user_id}", 60)
    return {"summary": await builder.write_summary(rt.llm, document)}


@router.post("/fix-all")
async def fix_all(document: ResumeDocument, request: Request, rt: URT) -> dict:
    """Proposed fixes for everything the check flags that can be fixed without new facts. Not saved."""
    await _limit(request, f"builder-fixall:{rt.user_id}", 20)
    return await builder.fix_all(rt.llm, document)


@router.get("/guides")
async def guides(user: CurrentUser) -> dict:
    """Which installed writing guides the AI uses (verified against their pinned checksums)."""
    return skillpacks.status()


class AtsBody(BaseModel):
    document: ResumeDocument
    job_id: int | None = None


@router.post("/ats-test")
async def ats(body: AtsBody, request: Request, db: DB, user: CurrentUser) -> dict:
    """Render the real files, run the ATS file checks, read both back and compare every fact; with a job,
    also which of its skills an ATS keyword search would find."""
    await _limit(request, f"builder-ats:{user.id}", 300)
    required = preferred = None
    if body.job_id is not None:
        job = await db.get(JobPosting, body.job_id)
        if job is None or job.user_id != user.id:
            raise ServiceError("not_found", "job not found", 404)
        parsed = ParsedJob.model_validate(job.parsed)
        required, preferred = parsed.required_skills, parsed.preferred_skills
    doc = builder.prepare(body.document, limits=False)
    return await run_in_threadpool(ats_test.run, doc, required, preferred)

"""Jobs: list and filter, details, manual import, evaluation, tailoring and lifecycle actions."""

from __future__ import annotations

import csv
import io
import secrets
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, Field, HttpUrl, StringConstraints, field_validator
from sqlalchemy import func, or_, select

from ..db import Application, JobMatch, JobPosting, JobSource, JobStatus, RecruiterContact, ResumeVersion
from ..domain import RawJob
from ..errors import ServiceError
from ..services import applications as app_service
from ..services.job_fetch import fetch_job
from ..services.jobs import evaluate_job, import_manual, latest_match
from ..services.tailoring import generate
from ..workflow.pipeline import advance
from ..workflow.states import MANUAL_STATES, TransitionError, transition
from .deps import DB, URT, CurrentUser, application_out, contact_out, get_owned, job_summary, match_out, version_out

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _latest_match_subquery():  # noqa: ANN202
    return select(JobMatch.job_id, func.max(JobMatch.id).label("mid")).group_by(JobMatch.job_id).subquery()


def _filtered(user_id: int, q: str | None, company: str | None, title: str | None, location: str | None, work_mode: str | None,
              min_score: float | None, max_score: float | None, min_salary: float | None, max_experience: float | None,
              source: str | None, status: str | None, posted_after: date | None, include_duplicates: bool):
    latest = _latest_match_subquery()
    query = (select(JobPosting, JobMatch)
             .outerjoin(latest, latest.c.job_id == JobPosting.id)
             .outerjoin(JobMatch, JobMatch.id == latest.c.mid)
             .join(JobSource, JobSource.id == JobPosting.source_id)
             .where(JobPosting.user_id == user_id))
    like = lambda v: f"%{v.lower()}%"  # noqa: E731 - bound parameters, never string-built SQL
    if q:
        query = query.where(or_(func.lower(JobPosting.title).like(like(q)), func.lower(JobPosting.company).like(like(q)),
                                func.lower(JobPosting.description_text).like(like(q))))
    if company:
        query = query.where(func.lower(JobPosting.company).like(like(company)))
    if title:
        query = query.where(func.lower(JobPosting.title).like(like(title)))
    if location:
        query = query.where(func.lower(JobPosting.location).like(like(location)))
    if work_mode:
        query = query.where(JobPosting.work_mode == work_mode)
    if min_score is not None:
        query = query.where(JobMatch.score >= min_score)
    if max_score is not None:
        query = query.where(JobMatch.score <= max_score)
    if min_salary is not None:
        query = query.where(JobPosting.salary_max_lpa >= min_salary)
    if max_experience is not None:
        query = query.where(or_(JobPosting.experience_min.is_(None), JobPosting.experience_min <= max_experience))
    if source:
        query = query.where(JobSource.key == source)
    if status:
        query = query.where(JobPosting.status.in_(status.split(",")))
    elif not include_duplicates:
        # The default list leaves out jobs you dismissed; filter by "Dismissed" to see them.
        query = query.where(JobPosting.status != JobStatus.WITHDRAWN)
    if posted_after:
        query = query.where(JobPosting.posted_at >= posted_after)
    if not include_duplicates:
        query = query.where(JobPosting.is_duplicate.is_(False))
    return query


@router.get("")
async def list_jobs(
    db: DB, user: CurrentUser, q: str | None = Query(None, max_length=120), company: str | None = Query(None, max_length=100),
    title: str | None = Query(None, max_length=100), location: str | None = Query(None, max_length=80),
    work_mode: str | None = Query(None, pattern="^(remote|hybrid|onsite)$"), min_score: float | None = Query(None, ge=0, le=100),
    max_score: float | None = Query(None, ge=0, le=100), min_salary: float | None = Query(None, ge=0, le=500),
    max_experience: float | None = Query(None, ge=0, le=40), source: str | None = Query(None, max_length=40),
    status: str | None = Query(None, max_length=400), posted_after: date | None = None, include_duplicates: bool = False,
    sort: str = Query("score", pattern="^(score|recent|posted)$"), page: int = Query(1, ge=1), page_size: int = Query(50, le=200),
) -> dict:
    query = _filtered(user.id, q, company, title, location, work_mode, min_score, max_score, min_salary, max_experience, source,
                      status, posted_after, include_duplicates)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    order = {"score": (JobMatch.score.desc().nulls_last(), JobPosting.id.desc()),
             "recent": (JobPosting.discovered_at.desc(),), "posted": (JobPosting.posted_at.desc().nulls_last(),)}[sort]
    rows = (await db.execute(query.order_by(*order).offset((page - 1) * page_size).limit(page_size))).all()
    return {"total": total, "items": [job_summary(job, match) for job, match in rows]}


@router.get("/export.csv")
async def export_jobs(db: DB, user: CurrentUser, status: str | None = None,
                      min_score: float | None = None) -> StreamingResponse:
    query = _filtered(user.id, None, None, None, None, None, min_score, None, None, None, None, status, None, True)
    rows = (await db.execute(query.order_by(JobPosting.id))).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "title", "company", "location", "work_mode", "source", "status", "score", "band", "salary",
                     "experience_min", "posted_at", "discovered_at", "url"])
    for job, match in rows:
        writer.writerow([job.id, _csv_safe(job.title), _csv_safe(job.company), _csv_safe(job.location or ""), job.work_mode,
                         job.source.key, job.status, match.score if match else "", match.band if match else "",
                         _csv_safe(job.salary_text or ""), job.experience_min, job.posted_at, job.discovered_at, job.url])
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=jobs.csv"})


def _csv_safe(value: str) -> str:
    """Neutralise spreadsheet formulas in untrusted text (CSV injection)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


@router.get("/{job_id}")
async def job_detail(job_id: int, db: DB, user: CurrentUser) -> dict:
    job = await get_owned(db, JobPosting, job_id, user, "job")
    match = await latest_match(db, job_id)
    versions = (await db.scalars(select(ResumeVersion).where(ResumeVersion.job_id == job_id)
                                 .order_by(ResumeVersion.version_no.desc()))).all()
    app = await db.scalar(select(Application).where(Application.job_id == job_id))
    contacts = (await db.scalars(select(RecruiterContact).where(RecruiterContact.job_id == job_id))).all()
    history = (await db.scalars(select(JobMatch).where(JobMatch.job_id == job_id).order_by(JobMatch.id.desc()).limit(10))).all()
    duplicates = (await db.scalars(select(JobPosting.id).where(JobPosting.user_id == user.id,
                                                               JobPosting.duplicate_of_id == job_id))).all()
    return {
        **job_summary(job, match),
        "description": job.description_text, "parsed": job.parsed, "employment_type": job.employment_type,
        "deadline": job.deadline.isoformat() if job.deadline else None, "apply_url": job.apply_url,
        "apply_email": job.apply_email, "questions": job.questions,
        "injection_snippets": (job.flags or {}).get("injection_snippets", []),
        "requirements": [{"kind": r.kind, "value": r.value} for r in job.requirements],
        "match": match_out(match), "score_history": [{"score": m.score, "at": m.created_at.isoformat()} for m in history],
        "resume_versions": [version_out(v) for v in versions],
        "application": application_out(app) if app else None,
        "recruiters": [contact_out(c) for c in contacts], "duplicates": list(duplicates),
    }


class ImportBody(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    company: str = Field(min_length=1, max_length=300)
    url: HttpUrl
    description: str = Field(min_length=30, max_length=100000)
    location: str | None = Field(default=None, max_length=300)
    work_mode: str | None = Field(default=None, pattern="^(remote|hybrid|onsite)$")
    apply_email: str | None = Field(default=None, max_length=320)
    recruiter_name: str | None = Field(default=None, max_length=200)
    recruiter_email: str | None = Field(default=None, max_length=320)
    questions: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]] = Field(
        default_factory=list, max_length=40)

    @field_validator("apply_email", "recruiter_email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        """Reported, not silently dropped: a mistyped address would otherwise just vanish."""
        if not value or not value.strip():
            return None
        try:
            return validate_email(value.strip(), check_deliverability=False).normalized.lower()
        except EmailNotValidError as exc:
            raise ValueError(f"not a valid email address ({exc})") from exc


class FetchBody(BaseModel):
    url: HttpUrl


@router.post("/fetch")
async def fetch_posting(body: FetchBody, request: Request, rt: URT) -> dict:
    """Read a posting link and return the fields for the import form. Nothing is saved."""
    if not await request.app.state.runtime.limiter.hit(f"job-fetch:{rt.user_id}", 30, 3600):
        raise ServiceError("rate_limited", "too many fetches this hour; try again later", 429)
    return (await fetch_job(rt.fetcher, str(body.url))).as_dict()


@router.post("/import", status_code=201)
async def import_job(body: ImportBody, db: DB, rt: URT) -> dict:
    raw = RawJob(external_id="manual-" + secrets.token_hex(8), url=str(body.url), title=body.title, company=body.company,
                 description=body.description, location=body.location, work_mode=body.work_mode,  # type: ignore[arg-type]
                 apply_email=body.apply_email, recruiter_name=body.recruiter_name, recruiter_email=body.recruiter_email,
                 questions=body.questions, posted_at=date.today())
    job = await import_manual(db, rt.settings, rt.user_id, raw)
    try:
        await evaluate_job(db, job)
    except ServiceError:
        pass  # no resume yet; evaluated once one is uploaded
    await db.commit()
    return {"id": job.id}


@router.post("/{job_id}/evaluate")
async def evaluate(job_id: int, db: DB, user: CurrentUser) -> dict:
    job = await get_owned(db, JobPosting, job_id, user, "job")
    match = await evaluate_job(db, job)
    await db.commit()
    return match_out(match) or {}


@router.post("/{job_id}/shortlist")
async def shortlist(job_id: int, db: DB, user: CurrentUser) -> dict:
    job = await get_owned(db, JobPosting, job_id, user, "job")
    if job.status == JobStatus.DISCOVERED:
        await evaluate_job(db, job)
    try:
        await transition(db, job, JobStatus.SHORTLISTED, reason="shortlisted by you", actor="user")
    except TransitionError as exc:
        raise ServiceError("bad_state", str(exc), 409) from exc
    await db.commit()
    return {"status": job.status}


@router.post("/{job_id}/tailor")
async def tailor_resume(job_id: int, db: DB, rt: URT, user: CurrentUser) -> dict:
    job = await get_owned(db, JobPosting, job_id, user, "job")
    if job.status == JobStatus.MATCH_EVALUATED:
        await transition(db, job, JobStatus.SHORTLISTED, reason="resume requested by you", actor="user")
    version = await generate(db, rt.settings, job, rt.llm, actor="user")
    await db.commit()
    return version_out(version, full=True)


@router.post("/{job_id}/application")
async def prepare_application(job_id: int, db: DB, rt: URT, user: CurrentUser) -> dict:
    job = await get_owned(db, JobPosting, job_id, user, "job")
    app = await app_service.prepare(db, rt, job, actor="user")
    await db.commit()
    return application_out(app)


@router.post("/{job_id}/process")
async def process(job_id: int, db: DB, rt: URT, user: CurrentUser) -> dict:
    """Run every pipeline stage this job is ready for, under the current policy."""
    job = await get_owned(db, JobPosting, job_id, user, "job")
    stages = await advance(db, rt, job)
    await db.commit()
    return {"stages": stages, "status": job.status}


class StatusBody(BaseModel):
    status: JobStatus
    note: str | None = Field(default=None, max_length=500)


@router.post("/{job_id}/status")
async def set_status(job_id: int, body: StatusBody, db: DB, user: CurrentUser) -> dict:
    job = await get_owned(db, JobPosting, job_id, user, "job")
    allowed = MANUAL_STATES | {JobStatus.MATCH_EVALUATED}  # MATCH_EVALUATED: undo a dismissal
    if body.status not in allowed:
        raise ServiceError("bad_status", "set this status through the matching action instead", 422)
    if body.status == JobStatus.MATCH_EVALUATED and job.status != JobStatus.WITHDRAWN:
        raise ServiceError("bad_state", "only a withdrawn job can be restored", 409)
    try:
        await transition(db, job, body.status, reason=body.note or "updated by you", actor="user")
    except TransitionError as exc:
        raise ServiceError("bad_state", str(exc), 409) from exc
    await db.commit()
    return {"status": job.status}

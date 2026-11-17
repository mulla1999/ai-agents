"""Application queue and tracker: approve, submit, retry, verify, confirm manual applications."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..applications.policy import Decision
from ..db import Application, ApprovalRequest, JobPosting, JobStatus, ResumeVersion
from ..services import applications as service
from ..errors import ServiceError
from .deps import DB, URT, CurrentUser, application_out, approval_out
from .jobs import _csv_safe

router = APIRouter(prefix="/api/applications", tags=["applications"])


async def _owned(db, rt, app_id: int) -> Application:  # noqa: ANN001
    app = await db.get(Application, app_id)
    if app is None or app.user_id != rt.user_id:  # someone else's application is "not found"
        raise ServiceError("not_found", "application not found", 404)
    return app

QUEUE_STATES = (JobStatus.AWAITING_APPROVAL, JobStatus.READY_TO_APPLY, JobStatus.APPLICATION_IN_PROGRESS,
                JobStatus.APPLICATION_FAILED, JobStatus.NEEDS_MANUAL)


async def _with_blockers(db, rt, app: Application) -> dict:  # noqa: ANN001
    out = application_out(app)
    version = await db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    decision: Decision = await service.decision_for(db, rt, app.job, app)
    blockers = service.approval_blockers(app, version, decision, service.route_for(rt, app.route).ready())
    out["approval_blockers"] = blockers
    # Warnings you may accept when approving; anything that blocks approval is listed only once.
    out["warnings"] = [r for r in decision.manual_reasons if r not in blockers and not r.startswith("question needs you")]
    out["auto_blockers"] = decision.auto_blockers
    out["resume_valid"] = bool(version and version.valid)
    return out


@router.get("/queue")
async def queue(db: DB, rt: URT) -> dict:
    apps = (await db.scalars(select(Application).join(JobPosting).where(Application.user_id == rt.user_id,
                                                                        JobPosting.status.in_(QUEUE_STATES))
                             .order_by(Application.updated_at.desc()))).all()
    approvals = (await db.scalars(select(ApprovalRequest).where(ApprovalRequest.user_id == rt.user_id,
                                                                ApprovalRequest.status == "pending")
                                  .order_by(ApprovalRequest.created_at.desc()))).all()
    ready = (await db.scalars(select(JobPosting).where(JobPosting.user_id == rt.user_id,
                                                       JobPosting.status == JobStatus.RESUME_READY))).all()
    return {"applications": [await _with_blockers(db, rt, a) for a in apps],
            "approvals": [approval_out(a) for a in approvals],
            "resume_ready_jobs": [{"id": j.id, "title": j.title, "company": j.company} for j in ready]}


@router.get("")
async def tracker(db: DB, user: CurrentUser, outcome: str | None = None, status: str | None = None) -> list[dict]:
    query = select(Application).join(JobPosting).where(Application.user_id == user.id).order_by(Application.updated_at.desc())
    if outcome:
        query = query.where(Application.outcome == outcome)
    if status:
        query = query.where(JobPosting.status.in_(status.split(",")))
    return [application_out(a) for a in (await db.scalars(query)).all()]


@router.get("/export.csv")
async def export(db: DB, user: CurrentUser) -> StreamingResponse:
    rows = (await db.scalars(select(Application).where(Application.user_id == user.id).order_by(Application.id))).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "job_id", "title", "company", "status", "outcome", "route", "mode", "submitted_at",
                     "confirmation_ref", "resume_file", "resume_sha256", "job_url"])
    for a in rows:
        writer.writerow([a.id, a.job_id, _csv_safe(a.job.title), _csv_safe(a.job.company), a.job.status, a.outcome,
                         a.route, a.mode, a.submitted_at, _csv_safe(a.confirmation_ref or ""),
                         (a.submitted_file_path or "").rsplit("/", 1)[-1], a.submitted_file_sha256 or "", a.job.url])
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=applications.csv"})


@router.get("/{app_id}")
async def detail(app_id: int, db: DB, rt: URT) -> dict:
    return await _with_blockers(db, rt, await _owned(db, rt, app_id))


class AnswerBody(BaseModel):
    answer_id: int
    answer: str = Field(max_length=5000)


@router.put("/{app_id}/answers")
async def answer(app_id: int, body: AnswerBody, db: DB, rt: URT) -> dict:
    app = await _owned(db, rt, app_id)
    await service.set_answer(db, app, body.answer_id, body.answer)
    await db.commit()
    return await _with_blockers(db, rt, app)


class NoteBody(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    submit_now: bool = True


@router.post("/{app_id}/approve")
async def approve(app_id: int, body: NoteBody, db: DB, rt: URT) -> dict:
    app = await _owned(db, rt, app_id)
    await service.approve(db, rt, app, body.note)
    await db.commit()
    if body.submit_now and app.route != "manual":
        await service.submit(db, rt, app, trigger="approved")
    return await _with_blockers(db, rt, app)


@router.post("/{app_id}/reject")
async def reject(app_id: int, body: NoteBody, db: DB, rt: URT) -> dict:
    app = await _owned(db, rt, app_id)
    await service.reject(db, app, body.note)
    await db.commit()
    return application_out(app)


@router.post("/{app_id}/hold")
async def hold(app_id: int, body: NoteBody, db: DB, rt: URT) -> dict:
    """Stop a scheduled automatic application; it moves to the approval queue."""
    app = await _owned(db, rt, app_id)
    await service.hold(db, app, body.note)
    await db.commit()
    return await _with_blockers(db, rt, app)


@router.post("/{app_id}/submit")
async def submit(app_id: int, db: DB, rt: URT) -> dict:
    app = await _owned(db, rt, app_id)
    await service.submit(db, rt, app, trigger="approved")
    return await _with_blockers(db, rt, app)


@router.post("/{app_id}/retry")
async def retry(app_id: int, db: DB, rt: URT) -> dict:
    app = await _owned(db, rt, app_id)
    await service.retry(db, rt, app)
    return await _with_blockers(db, rt, app)


@router.post("/{app_id}/verify")
async def verify(app_id: int, db: DB, rt: URT) -> dict:
    app = await _owned(db, rt, app_id)
    result = await service.verify_unknown(db, rt, app)
    await db.commit()
    return {"result": result, "application": await _with_blockers(db, rt, app)}


class ConfirmBody(BaseModel):
    reference: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=500)


@router.post("/{app_id}/confirm-manual")
async def confirm_manual(app_id: int, body: ConfirmBody, db: DB, rt: URT) -> dict:
    app = await _owned(db, rt, app_id)
    await service.confirm_manual(db, rt, app, (body.reference or "").strip() or None, body.note)
    await db.commit()
    return await _with_blockers(db, rt, app)

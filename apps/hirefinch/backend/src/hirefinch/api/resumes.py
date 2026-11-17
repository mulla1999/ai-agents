"""Master resumes (upload, choose, correct) and tailored versions (preview, download)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import ResumeMaster, ResumeVersion
from ..domain import ResumeDocument
from ..errors import ServiceError
from ..resume.parser import MAX_UPLOAD_BYTES
from ..resume.tailor import render_text
from ..services import resumes as service
from ..services.integrations import platform_config
from ..services.resumes import document_of
from ..services.settings_store import get_profile
from ..text import resume_filename, sha256_file
from .deps import DB, URT, CurrentUser, get_owned, iso, master_out, version_out

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


def _local_only(rt, user) -> None:  # noqa: ANN001
    """Listing or importing files from the server's own disk: superadmin, development only."""
    if rt.settings.environment == "production" or user.role != "superadmin":
        raise ServiceError("forbidden", "importing files from the server is not available; upload your resume instead", 403)


@router.get("/masters")
async def list_masters(db: DB, user: CurrentUser) -> list[dict]:
    rows = (await db.scalars(select(ResumeMaster).where(ResumeMaster.user_id == user.id, ResumeMaster.archived_at.is_(None))
                             .order_by(ResumeMaster.uploaded_at.desc()))).all()
    return [master_out(m) for m in rows]


@router.post("/masters", status_code=201)
async def upload_master(db: DB, rt: URT, file: UploadFile = File(...)) -> dict:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    limits = await platform_config(db, "limits")
    master = await service.store_master(db, rt.settings, rt.user_id, data, file.filename or "resume",
                                        max_resumes=int(limits["max_resumes"]))
    await db.commit()
    return master_out(master, full=True)


@router.get("/candidates")
async def resume_candidates(rt: URT, user: CurrentUser) -> dict:
    _local_only(rt, user)
    found = service.find_candidates(rt.settings)
    return {"search_paths": [str(p) for p in rt.settings.resume_search_dirs],
            "files": [{"path": c.path, "name": c.name, "size": c.size, "modified": iso(c.modified)} for c in found]}


class ImportPath(BaseModel):
    path: str = Field(min_length=1, max_length=1024)


@router.post("/masters/import", status_code=201)
async def import_master(body: ImportPath, db: DB, rt: URT, user: CurrentUser) -> dict:
    _local_only(rt, user)
    path = service.candidate_allowed(rt.settings, body.path)
    if path.stat().st_size > MAX_UPLOAD_BYTES:
        raise ServiceError("too_large", "resume files must be 5 MB or smaller", 413)
    master = await service.store_master(db, rt.settings, rt.user_id, path.read_bytes(), path.name)
    await db.commit()
    return master_out(master, full=True)


@router.get("/masters/{master_id}")
async def get_master(master_id: int, db: DB, user: CurrentUser) -> dict:
    master = await get_owned(db, ResumeMaster, master_id, user, "resume")
    return {**master_out(master, full=True), "text": render_text(document_of(master))}


@router.post("/masters/{master_id}/activate")
async def activate_master(master_id: int, db: DB, user: CurrentUser) -> dict:
    master = await service.activate(db, user.id, master_id)
    await db.commit()
    return master_out(master)


@router.delete("/masters/{master_id}")
async def delete_master(master_id: int, db: DB, user: CurrentUser) -> dict:
    outcome = await service.remove(db, user.id, master_id)
    await db.commit()
    return {"result": outcome}


@router.post("/masters/{master_id}/reread")
async def reread_master(master_id: int, db: DB, user: CurrentUser) -> dict:
    master = await service.reread(db, user.id, master_id)
    await db.commit()
    return master_out(master, full=True)


@router.put("/masters/{master_id}/document")
async def correct_master(master_id: int, document: ResumeDocument, db: DB, user: CurrentUser) -> dict:
    master = await service.correct(db, user.id, master_id, document)
    await db.commit()
    return master_out(master, full=True)


@router.get("/masters/{master_id}/file")
async def master_file(master_id: int, db: DB, user: CurrentUser) -> FileResponse:
    master = await get_owned(db, ResumeMaster, master_id, user, "resume")
    return FileResponse(master.file_path, filename=master.filename)


async def _jobs_for(db, user_id: int, job_ids: set[int]) -> dict[int, dict]:  # noqa: ANN001
    """Title, company, location, status and latest score for each job, so a resume is shown by its job."""
    from ..db import JobMatch, JobPosting
    from .jobs import _latest_match_subquery

    if not job_ids:
        return {}
    latest = _latest_match_subquery()
    rows = (await db.execute(
        select(JobPosting, JobMatch).outerjoin(latest, latest.c.job_id == JobPosting.id)
        .outerjoin(JobMatch, JobMatch.id == latest.c.mid)
        .where(JobPosting.user_id == user_id, JobPosting.id.in_(job_ids)))).all()
    return {j.id: {"title": j.title, "company": j.company, "location": j.location, "status": j.status, "url": j.url,
                   "score": round(m.score) if m and m.score is not None else None, "band": m.band if m else None}
            for j, m in rows}


@router.get("/versions")
async def list_versions(db: DB, user: CurrentUser, job_id: int | None = None) -> list[dict]:
    query = select(ResumeVersion).where(ResumeVersion.user_id == user.id).order_by(ResumeVersion.created_at.desc()).limit(200)
    if job_id is not None:
        query = query.where(ResumeVersion.job_id == job_id)
    versions = (await db.scalars(query)).all()
    jobs = await _jobs_for(db, user.id, {v.job_id for v in versions})
    return [{**version_out(v), "job": jobs.get(v.job_id)} for v in versions]


@router.get("/versions/{version_id}")
async def get_version(version_id: int, db: DB, user: CurrentUser) -> dict:
    version = await get_owned(db, ResumeVersion, version_id, user, "resume version")
    master = await db.get(ResumeMaster, version.master_id)
    jobs = await _jobs_for(db, user.id, {version.job_id})
    siblings = (await db.scalars(select(ResumeVersion).where(ResumeVersion.job_id == version.job_id)
                                 .order_by(ResumeVersion.version_no.desc()))).all()
    return {**version_out(version, full=True), "job": jobs.get(version.job_id),
            "versions": [{"id": x.id, "version_no": x.version_no, "valid": x.valid, "created_at": iso(x.created_at)} for x in siblings],
            "text": render_text(ResumeDocument.model_validate(version.content)),
            "master_text": render_text(document_of(master)) if master else ""}


@router.get("/versions/{version_id}/download")
async def download_version(version_id: int, db: DB, user: CurrentUser,
                           format: str = Query("pdf", pattern="^(pdf|docx)$")) -> FileResponse:
    version = await get_owned(db, ResumeVersion, version_id, user, "resume version")
    path, sha = (version.pdf_path, version.pdf_sha256) if format == "pdf" else (version.docx_path, version.docx_sha256)
    if not Path(path).is_file() or sha256_file(path) != sha:
        raise ServiceError("file_changed", "the stored file is missing or no longer matches its checksum", 410)
    media = "application/pdf" if format == "pdf" else \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    # inline for the PDF preview iframe; attachment for downloads.
    profile = await get_profile(db, user.id)
    name = profile.full_name or ((version.content or {}).get("contact") or {}).get("name")
    return FileResponse(path, media_type=media, filename=resume_filename(name, Path(path).suffix),  # First_Last_Resume.pdf
                        content_disposition_type="inline" if format == "pdf" else "attachment")

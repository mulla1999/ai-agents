"""Master resumes: upload, choose the active one, correct the parse.

The uploaded file is copied into ``data_dir/masters`` with read-only permissions and never written
again. Corrections are stored separately and used in place of the automatic parse.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import ResumeMaster, ResumeTailoringRun, ResumeVersion, utcnow
from ..domain import ResumeDocument
from ..errors import ServiceError
from ..resume.parser import MAX_UPLOAD_BYTES, ResumeParseError, parse_resume
from ..text import sha256_text
from .audit import record

_NAME_HINTS = ("resume", "cv", "curriculum")


@dataclass
class Candidate:
    path: str
    name: str
    size: int
    modified: datetime


def document_of(master: ResumeMaster) -> ResumeDocument:
    return ResumeDocument.model_validate(master.corrected or master.parsed)


async def active_master(db: AsyncSession, user_id: int) -> ResumeMaster | None:
    return await db.scalar(select(ResumeMaster).where(ResumeMaster.user_id == user_id, ResumeMaster.is_active.is_(True)))


async def store_master(db: AsyncSession, settings: Settings, user_id: int, data: bytes, filename: str,
                       *, max_resumes: int = 50) -> ResumeMaster:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ServiceError("too_large", "resume files must be 5 MB or smaller", 413)
    try:
        fmt, parsed = parse_resume(data, filename)
    except ResumeParseError as exc:
        raise ServiceError("invalid_resume", str(exc), 422) from exc
    digest = hashlib.sha256(data).hexdigest()
    existing = await db.scalar(select(ResumeMaster).where(ResumeMaster.user_id == user_id, ResumeMaster.sha256 == digest))
    if existing is not None:
        existing.archived_at = None  # uploading a deleted resume again brings it back
        return existing
    count = await db.scalar(select(func.count(ResumeMaster.id)).where(ResumeMaster.user_id == user_id,
                                                                      ResumeMaster.archived_at.is_(None)))
    if (count or 0) >= max_resumes:
        raise ServiceError("limit", f"you can keep up to {max_resumes} master resumes; delete one first", 409)
    folder = settings.data_dir / "masters" / str(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{digest[:16]}.{fmt}"
    if not target.exists():
        target.write_bytes(data)
        os.chmod(target, stat.S_IRUSR | stat.S_IRGRP)  # read-only: the master is never modified
    master = ResumeMaster(
        user_id=user_id,
        filename=Path(filename).name[:255],
        file_path=str(target),
        file_format=fmt,
        sha256=digest,
        parsed=parsed.model_dump(mode="json"),
        is_active=False,
    )
    db.add(master)
    await db.flush()
    if await active_master(db, user_id) is None:
        master.is_active = True
    await record(db, user_id, "resume.uploaded", f"master resume uploaded ({fmt}, {len(parsed.warnings)} parse warnings)",
                 actor="user", entity=("resume_master", master.id), details={"sha256": digest})
    return master


async def activate(db: AsyncSession, user_id: int, master_id: int) -> ResumeMaster:
    master = await db.get(ResumeMaster, master_id)
    if master is None or master.user_id != user_id or master.archived_at is not None:
        raise ServiceError("not_found", "resume not found", 404)
    await db.execute(update(ResumeMaster).where(ResumeMaster.user_id == user_id).values(is_active=False))
    master.is_active = True
    await record(db, user_id, "resume.activated", f"master resume {master.filename} is now active", actor="user",
                 entity=("resume_master", master.id))
    return master


async def correct(db: AsyncSession, user_id: int, master_id: int, document: ResumeDocument) -> ResumeMaster:
    master = await db.get(ResumeMaster, master_id)
    if master is None or master.user_id != user_id:
        raise ServiceError("not_found", "resume not found", 404)
    document.warnings = []
    master.corrected = document.model_dump(mode="json")
    await record(db, user_id, "resume.corrected", "master resume parse corrected", actor="user",
                 entity=("resume_master", master.id), details={"content_sha256": sha256_text(document.model_dump_json())})
    return master


async def remove(db: AsyncSession, user_id: int, master_id: int) -> str:
    """Delete a master resume you no longer want. Returns "deleted" or "archived".

    The resume in use can't be removed (choose another first). One that tailored resumes were made
    from is archived instead: hidden from your list, but kept so those resumes and their records stay
    valid. Anything else is deleted together with its stored file."""
    master = await db.get(ResumeMaster, master_id)
    if master is None or master.user_id != user_id or master.archived_at is not None:
        raise ServiceError("not_found", "resume not found", 404)
    if master.is_active:
        raise ServiceError("in_use", "this is the resume in use; choose another one first, then delete this one", 409)
    used = await db.scalar(select(func.count(ResumeVersion.id)).where(ResumeVersion.master_id == master.id)) or 0
    used += await db.scalar(select(func.count(ResumeTailoringRun.id)).where(ResumeTailoringRun.master_id == master.id)) or 0
    if used:
        master.archived_at = utcnow()
        await record(db, user_id, "resume.archived", f"master resume {master.filename} removed from the list (kept for "
                     f"{used} tailored resume records)", actor="user", entity=("resume_master", master.id))
        return "archived"
    path, name = master.file_path, master.filename
    await db.delete(master)
    await db.flush()
    # The same file may back another row only for another user (sha256 is unique per user), and each
    # user has their own folder, so the file is this resume's alone.
    with contextlib.suppress(FileNotFoundError):
        Path(path).unlink()
    await record(db, user_id, "resume.deleted", f"master resume {name} deleted", actor="user")
    return "deleted"


async def reread(db: AsyncSession, user_id: int, master_id: int) -> ResumeMaster:
    """Read a stored resume again with the current reader (after the reader improves). Your own
    corrections, if any, are kept and still win."""
    master = await db.get(ResumeMaster, master_id)
    if master is None or master.user_id != user_id or master.archived_at is not None:
        raise ServiceError("not_found", "resume not found", 404)
    try:
        _, parsed = parse_resume(Path(master.file_path).read_bytes(), master.filename)
    except FileNotFoundError as exc:
        raise ServiceError("file_missing", "the stored file for this resume is missing; upload it again", 410) from exc
    except ResumeParseError as exc:
        raise ServiceError("invalid_resume", str(exc), 422) from exc
    master.parsed = parsed.model_dump(mode="json")
    await record(db, user_id, "resume.reread", f"master resume {master.filename} read again "
                 f"({len(parsed.warnings)} warnings)", actor="user", entity=("resume_master", master.id))
    return master


def find_candidates(settings: Settings, max_depth: int = 3) -> list[Candidate]:
    """List likely resume files (names only) under the configured folders. Nothing is read."""
    found: list[Candidate] = []
    for root in settings.resume_search_dirs:
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = len(Path(dirpath).parts) - base_depth
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", ".venv")]
            if depth >= max_depth:
                dirnames[:] = []
            for name in filenames:
                lower = name.lower()
                if lower.endswith((".pdf", ".docx")) and any(h in lower for h in _NAME_HINTS):
                    path = Path(dirpath) / name
                    info = path.stat()
                    found.append(Candidate(str(path), name, info.st_size, datetime.fromtimestamp(info.st_mtime, UTC)))
    return sorted(found, key=lambda c: c.modified, reverse=True)


def candidate_allowed(settings: Settings, path: str) -> Path:
    """Only files the candidate finder would list may be imported by path."""
    resolved = Path(path).resolve()
    for root in settings.resume_search_dirs:
        if resolved.is_relative_to(root.resolve()) and resolved.suffix.lower() in (".pdf", ".docx"):
            if any(h in resolved.name.lower() for h in _NAME_HINTS) and resolved.is_file():
                return resolved
    raise ServiceError("forbidden_path", "that file is not in a configured resume folder", 403)

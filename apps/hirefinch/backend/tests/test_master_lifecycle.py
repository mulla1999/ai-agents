"""Old master resumes: headings worded your own way, reading a resume again, and deleting old ones safely."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from hirefinch.db import ResumeMaster, ResumeTailoringRun
from hirefinch.resume.parser import Line, _heading
from hirefinch.services import resumes as service

from .test_assistant import _job


@pytest.mark.parametrize("text, section", [
    ("CORE TECHNICAL SKILLS", "skills"), ("Core Technical Skills", "skills"), ("TECH STACK", "skills"),
    ("RELEVANT WORK EXPERIENCE", "experience"), ("Relevant Work Experience:", "experience"),
    ("Academic Qualifications:", "education"),
    # Not headings: a job title, a project name, a link label, a sentence.
    ("Head of Customer Experience", None), ("Order History", None), ("LinkedIn Profile", None), ("5 years of experience", None),
])
def test_headings_worded_your_own_way(text, section):
    assert _heading(Line(text)) == section


async def _upload(urt, data: bytes, name: str) -> int:
    async with urt.sessionmaker() as db:
        master = await service.store_master(db, urt.settings, urt.user_id, data, name)
        await db.commit()
        return master.id


async def test_delete_removes_an_unused_old_resume_and_its_file(client, urt, resume_docx, resume_pdf):
    in_use = await _upload(urt, resume_docx, "cv.docx")
    old = await _upload(urt, resume_pdf, "old.pdf")
    async with urt.sessionmaker() as db:
        path = Path((await db.get(ResumeMaster, old)).file_path)
    assert path.exists()
    assert (await client.delete(f"/api/resumes/masters/{in_use}")).status_code == 409  # the one in use
    r = await client.delete(f"/api/resumes/masters/{old}")
    assert r.status_code == 200 and r.json() == {"result": "deleted"}
    assert not path.exists()
    assert [m["id"] for m in (await client.get("/api/resumes/masters")).json()] == [in_use]


async def test_delete_archives_a_resume_tailored_resumes_came_from(client, urt, resume_docx, resume_pdf):
    job_id = await _job(urt, resume_docx)  # uploads resume_docx, which becomes the one in use
    old = await _upload(urt, resume_pdf, "old.pdf")
    async with urt.sessionmaker() as db:
        db.add(ResumeTailoringRun(user_id=urt.user_id, job_id=job_id, master_id=old, template_version="t", status="succeeded"))
        await db.commit()
    r = await client.delete(f"/api/resumes/masters/{old}")
    assert r.json() == {"result": "archived"}
    assert old not in [m["id"] for m in (await client.get("/api/resumes/masters")).json()]
    async with urt.sessionmaker() as db:
        kept = await db.get(ResumeMaster, old)
        assert kept is not None and kept.archived_at is not None and Path(kept.file_path).exists()
        assert await db.scalar(select(ResumeTailoringRun).where(ResumeTailoringRun.master_id == old)) is not None
    # Uploading the same file again brings it back.
    assert await _upload(urt, resume_pdf, "old.pdf") == old
    assert old in [m["id"] for m in (await client.get("/api/resumes/masters")).json()]


async def test_read_again_refreshes_the_parse(client, urt, resume_docx):
    master_id = await _upload(urt, resume_docx, "cv.docx")
    async with urt.sessionmaker() as db:
        (await db.get(ResumeMaster, master_id)).parsed = {"warnings": ["no skills section found"]}
        await db.commit()
    r = await client.post(f"/api/resumes/masters/{master_id}/reread")
    assert r.status_code == 200
    assert "no skills section found" not in r.json()["warnings"] and r.json()["skills_count"] > 0

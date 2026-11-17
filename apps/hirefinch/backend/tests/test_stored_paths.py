"""File locations are stored relative to the data/artifacts folders, so moving the install keeps them working."""

from __future__ import annotations

import pytest

from hirefinch.db import paths


@pytest.fixture
def roots(tmp_path):
    paths.configure(tmp_path / "data", tmp_path / "artifacts")
    yield tmp_path
    paths._roots = None  # back to the default for other tests


def test_paths_under_the_app_folders_are_stored_relative(roots):
    pdf = roots / "artifacts" / "users" / "1" / "resumes" / "acme" / "job-7" / "v1" / "resume.pdf"
    assert paths.to_stored(str(pdf)) == "artifacts:users/1/resumes/acme/job-7/v1/resume.pdf"
    assert paths.to_stored(str(roots / "data" / "masters" / "1" / "x.pdf")) == "data:masters/1/x.pdf"
    assert paths.from_stored("artifacts:users/1/resumes/acme/job-7/v1/resume.pdf") == str(pdf)


def test_moving_the_install_keeps_stored_paths_working(roots, tmp_path):
    stored = paths.to_stored(str(roots / "data" / "masters" / "1" / "x.pdf"))
    moved = tmp_path / "renamed-install"
    paths.configure(moved / "data", moved / "artifacts")
    assert paths.from_stored(stored) == str(moved / "data" / "masters" / "1" / "x.pdf")


def test_other_values_pass_through_and_traversal_is_refused(roots):
    assert paths.to_stored("/somewhere/else/file.pdf") == "/somewhere/else/file.pdf"
    assert paths.from_stored("/somewhere/else/file.pdf") == "/somewhere/else/file.pdf"
    assert paths.to_stored(None) is None and paths.from_stored(None) is None
    with pytest.raises(ValueError):
        paths.from_stored("data:../../etc/passwd")


async def test_columns_round_trip_through_the_database(roots, sessionmaker, user_id):
    from sqlalchemy import text

    from hirefinch.db import ResumeMaster

    target = roots / "data" / "masters" / str(user_id) / "cv.pdf"
    async with sessionmaker() as db:
        master = ResumeMaster(user_id=user_id, filename="cv.pdf", file_path=str(target), file_format="pdf", sha256="0" * 64)
        db.add(master)
        await db.commit()
        master_id = master.id
        raw = await db.scalar(text("SELECT file_path FROM resume_master WHERE id = :id"), {"id": master_id})
        assert raw == f"data:masters/{user_id}/cv.pdf"
    async with sessionmaker() as db:
        assert (await db.get(ResumeMaster, master_id)).file_path == str(target)

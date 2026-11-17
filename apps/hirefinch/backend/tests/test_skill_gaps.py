"""Skills jobs ask for that the resume doesn't show: asking once, remembering, and re-scoring."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from hirefinch.db import JobPosting, JobSource
from hirefinch.domain import Profile, RawJob
from hirefinch.services import settings_store as store
from hirefinch.services.jobs import ensure_sources, evaluate_job, ingest
from hirefinch.services.resumes import store_master

# Asks for two skills the test resume doesn't have.
JD = ("Requirements\n- 3+ years of experience\n- Java, Spring Boot, Kafka, Kotlin, Rust, MySQL\n"
      "Salary: 30-40 LPA. Hybrid, Pune.")


async def _job(rt, resume_docx, external_id="g1", title="Backend Engineer") -> int:
    async with rt.sessionmaker() as db:
        await ensure_sources(db, rt.user_id)
        await store_master(db, rt.settings, rt.user_id, resume_docx, "cv.docx")
        await store.save_profile(db, rt.user_id, Profile(notification_email="me@example.com"))
        source = await db.scalar(select(JobSource).where(JobSource.key == "mock", JobSource.user_id == rt.user_id))
        raw = RawJob(posted_at=date.today(), external_id=external_id, url=f"https://jobs.example.com/{external_id}", title=title,
                     company=f"Gap Co {external_id}", description=JD, location="Pune", apply_method="mock")
        stats = await ingest(db, rt.settings, source, [raw], await store.get_preferences(db, rt.user_id))
        await evaluate_job(db, await db.get(JobPosting, stats.new_ids[0]))
        await db.commit()
        return stats.new_ids[0]


async def _score(client, job_id: int) -> float:
    return (await client.get(f"/api/jobs/{job_id}")).json()["match"]["score"]


async def test_saying_yes_adds_the_skill_and_rescores_every_job_that_asked(client, urt, resume_docx):
    first = await _job(urt, resume_docx)
    second = await _job(urt, resume_docx, external_id="g2", title="Platform Engineer")
    gaps = (await client.get(f"/api/jobs/{first}/skill-gaps")).json()
    required = [g["skill"] for g in gaps if g["required"]]
    assert required, gaps
    skill = required[0]
    top = (await client.get("/api/skills/gaps")).json()
    assert {"skill": skill, "jobs": 2} in top

    before = await _score(client, first)
    r = await client.post("/api/skills/answer", json={"skill": skill, "knows": True, "evidence": "Used daily at Example Bank"})
    assert r.status_code == 200 and r.json()["rescored"] == 2
    assert await _score(client, first) > before
    assert skill not in [g["skill"] for g in (await client.get(f"/api/jobs/{second}/skill-gaps")).json()]
    profile = (await client.get("/api/profile")).json()["profile"]
    assert any(s["name"] == skill for s in profile["verified_extra_skills"])


async def test_saying_no_is_remembered_and_not_asked_again(client, urt, resume_docx):
    job_id = await _job(urt, resume_docx)
    skill = next(g["skill"] for g in (await client.get(f"/api/jobs/{job_id}/skill-gaps")).json() if g["required"])
    r = await client.post("/api/skills/answer", json={"skill": skill, "knows": False})
    assert r.json() == {"skill": skill, "knows": False, "rescored": 0}
    assert next(g for g in (await client.get(f"/api/jobs/{job_id}/skill-gaps")).json() if g["skill"] == skill)["declined"]
    assert skill not in [g["skill"] for g in (await client.get("/api/skills/gaps")).json()]


async def test_yes_needs_a_word_on_where(client, urt, resume_docx):
    await _job(urt, resume_docx)
    r = await client.post("/api/skills/answer", json={"skill": "Kotlin", "knows": True, "evidence": ""})
    assert r.status_code == 422 and "where you used it" in r.json()["message"]

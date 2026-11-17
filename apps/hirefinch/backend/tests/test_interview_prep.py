"""Interview prep: useful without AI, and AI stories may only use facts from your own bullets."""

from __future__ import annotations

from agents_core.llm.testing import ScriptedLLM

from hirefinch.db import ResumeMaster
from hirefinch.services.resumes import document_of

from .conftest import make_user, signed_in
from .test_assistant import _job


async def test_basic_prep_without_ai_uses_your_own_bullets(client, urt, resume_docx):
    job_id = await _job(urt, resume_docx)
    assert (await client.get(f"/api/jobs/{job_id}/interview-prep")).json() == {"prep": None}
    r = await client.post(f"/api/jobs/{job_id}/interview-prep")
    assert r.status_code == 200, r.text
    prep = r.json()["prep"]
    assert prep["used_llm"] is False and prep["ask"] and prep["role"]
    java = next(t for t in prep["technical"] if t["skill"] == "Java")
    assert java["your_points"] and all("text" in p for p in java["your_points"])
    assert (await client.get(f"/api/jobs/{job_id}/interview-prep")).json()["prep"]["technical"] == prep["technical"]


async def test_ai_stories_with_invented_facts_are_left_out(client, urt, runtime, resume_docx):
    job_id = await _job(urt, resume_docx)
    async with urt.sessionmaker() as db:
        from sqlalchemy import select

        doc = document_of(await db.scalar(select(ResumeMaster).where(ResumeMaster.user_id == urt.user_id)))
    bullet = doc.experience[0].bullets[0]
    runtime.llm_override = ScriptedLLM([{
        "questions": [{"question": "How do you design a Kafka consumer for retries?", "type": "technical", "why": "event-driven work"}],
        "stories": [
            {"title": "A real one", "bullet_ids": [bullet.id], "situation": "The team needed it.", "task": "Own the change.",
             "action": bullet.text, "result": "It shipped.", "good_for": ["ownership"]},
            {"title": "Invented", "bullet_ids": [bullet.id], "situation": "x", "task": "y",
             "action": bullet.text, "result": "Saved 97% of costs for 4000 users", "good_for": []},
        ],
        "ask": ["How is on-call shared?"],
    }])
    try:
        prep = (await client.post(f"/api/jobs/{job_id}/interview-prep")).json()["prep"]
    finally:
        runtime.llm_override = None
    assert prep["used_llm"] is True
    assert [s["title"] for s in prep["stories"]] == ["A real one"] and prep["stories"][0]["sources"] == [bullet.text]
    assert "1 suggested story left out" in prep["note"]
    assert prep["ask"] == ["How is on-call shared?"] and prep["questions"][0]["type"] == "technical"


async def test_someone_elses_job_is_not_found(app, client, urt, sessionmaker, resume_docx):
    job_id = await _job(urt, resume_docx)
    await make_user(sessionmaker, "other@example.com")
    other = await signed_in(app, "other@example.com")
    assert (await other.post(f"/api/jobs/{job_id}/interview-prep")).status_code == 404
    await other.aclose()

"""ATS parse test: the real files are rendered, read back and compared fact by fact."""

from __future__ import annotations

from hirefinch.domain import ResumeDocument
from hirefinch.resume import ats_test
from hirefinch.resume.parser import Line, _is_continuation, _Parser

from .test_resume_builder import DOC


def test_a_clean_resume_reads_back_completely():
    doc = ResumeDocument.model_validate({**DOC, "experience": [{**DOC["experience"][0], "id": "e1", "date_text": "Jun 2021 – Present",
                                                                "bullets": [{"id": "b1", "text": b["text"]} for b in DOC["experience"][0]["bullets"]]}]})
    result = ats_test.run(doc, ["Java", "Kotlin"], ["Docker"])
    read = result["readability"]
    assert read["score"] == 100, read
    assert read["files"]["PDF"]["read"] == read["files"]["PDF"]["total"] and read["files"]["Word"]["misses"] == []
    assert all(c["ok"] for c in read["checks"])
    assert result["keywords"]["required_found"] == ["Java"] and result["keywords"]["required_missing"] == ["Kotlin"]


def test_lost_facts_are_reported_not_hidden():
    source = ResumeDocument.model_validate({**DOC, "experience": [
        {"id": "e1", "title": "Software Engineer", "company": "Acme", "date_text": "2021 – Present", "is_current": True,
         "bullets": [{"id": "b1", "text": "Built the payments API"}]}]})
    read = source.model_copy(deep=True)
    read.contact.phone = None
    read.experience[0].bullets = []
    misses = {f["fact"] for f in ats_test.compare(source, read) if not f["ok"]}
    assert "Phone" in misses and any("Built the payments API" in m for m in misses)


def test_a_role_heading_after_a_wrapped_bullet_starts_a_new_role():
    # The bullet wrapped without a full stop; the next line is the next role, not more of the bullet.
    assert not _is_continuation("Secured services with Spring Security and Azure Key Vault",
                                Line("Associate Software Engineer November 2022 – January 2024"))
    assert _is_continuation("Reduced latency across", Line("the order service by 35%"))


def test_wrapped_skill_lines_keep_items_whole():
    parser = _Parser([])
    parser._skills([Line("Backend: Java, Spring Boot, Apache"), Line("Kafka, MySQL")])
    assert parser.doc.skills[0].items == ["Java", "Spring Boot", "Apache Kafka", "MySQL"]


async def test_endpoint_runs_on_a_draft_over_the_save_limits(client):
    long_role = {**DOC["experience"][0], "bullets": [{"id": "", "text": f"Built internal service number {i} for payments"} for i in range(14)]}
    r = await client.post("/api/resume-builder/ats-test", json={"document": {**DOC, "experience": [long_role]}})
    assert r.status_code == 200, r.text
    assert r.json()["readability"]["score"] >= 90 and "keywords" not in r.json()

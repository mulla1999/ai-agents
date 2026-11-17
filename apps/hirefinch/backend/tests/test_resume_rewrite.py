"""LLM bullet rewording: only rewrites that keep to the facts are used, and the files stay ATS-safe."""

from __future__ import annotations

from datetime import date

import docx
import pypdf
import pytest
from agents_core.llm.testing import ScriptedLLM

from hirefinch.candidate import build_candidate
from hirefinch.domain import Profile, RawJob
from hirefinch.jobs.parser import parse_job
from hirefinch.resume.render import render_resume
from hirefinch.resume.tailor import tailor
from hirefinch.resume.validator import rewrite_problem, validate_facts, validate_files
from hirefinch.services.tailoring import _reword_bullets

ORIGINAL = "Built Java 17 Spring Boot microservices with Kafka event-driven pipelines."
JD = ("What you'll do\n- Build event-driven microservices\nRequirements\n- Java, Spring Boot, Kafka, Hibernate, MySQL\n- 3+ years of experience")


@pytest.mark.parametrize(("rewritten", "reason"), [
    ("Delivered event-driven pipelines on Kafka by building Java 17 Spring Boot microservices.", None),
    ("Built Java 17 Spring Boot microservices with Kafka pipelines, cutting latency by 40%.", "numbers"),
    ("Built Java 21 Spring Boot microservices with Kafka event-driven pipelines.", "numbers"),
    ("Built Java 17 Spring Boot microservices with Kafka and Kubernetes event-driven pipelines.", "adds technologies"),
    ("Built Java 17 Spring Boot microservices with event-driven pipelines.", "drops technologies"),
    ("Led a team building Java 17 Spring Boot microservices with Kafka event-driven pipelines.", "claims more"),
    ("I built Java 17 Spring Boot microservices with Kafka event-driven pipelines.", "first person"),
    ("Built Java 17 Spring Boot microservices with Kafka event-driven pipelines for Google.", "adds a name"),
    ("Java 17 Spring Boot Kafka.", "length"),
])
def test_rewrite_rules(rewritten, reason):
    problem = rewrite_problem(ORIGINAL, rewritten)
    assert (problem is None) if reason is None else (problem is not None and reason in problem), problem


@pytest.fixture
def setup(resume_doc):
    parsed = parse_job(RawJob(external_id="1", url="https://x.example/1", title="Backend Engineer", company="Acme", description=JD), JD)
    candidate = build_candidate(resume_doc, Profile(), today=date(2026, 9, 1))
    result = tailor(resume_doc, parsed, candidate, Profile(), role_family="java_backend")
    return result, parsed, candidate


async def test_llm_rewrites_are_kept_only_when_they_pass(setup, resume_doc, tmp_path):
    result, parsed, candidate = setup
    good = "Delivered event-driven pipelines on Kafka by building Java 17 Spring Boot microservices."
    llm = ScriptedLLM([{"bullets": [{"id": "e1b1", "text": good},
                                    {"id": "e2b1", "text": "Developed 50+ REST APIs with Hibernate and MySQL."},  # inflated figure
                                    {"id": "nope", "text": "Injected bullet."}]}])
    note = await _reword_bullets(llm, result, parsed, resume_doc)
    bullets = {b.id: b for e in result.document.experience for b in e.bullets}
    assert bullets["e1b1"].text == good and bullets["e1b1"].source == ORIGINAL
    assert bullets["e2b1"].text == "Developed 20+ REST APIs with Hibernate and MySQL."  # master wording kept
    assert "nope" not in bullets and "1 bullets reworded, 1 rewordings rejected" in note
    assert result.rejected_rewrites[0]["reason"].startswith("numbers")
    assert "reworded by the LLM" in " ".join(result.changes) and good in result.diff
    # The whole document still passes the fact check and the ATS file checks.
    report = validate_facts(resume_doc, result.document, Profile(), max_years=candidate.years_including_internships)
    rendered = render_resume(result.document, tmp_path / "r.docx", tmp_path / "r.pdf")
    validate_files(report, tmp_path / "r.docx", tmp_path / "r.pdf", result.document, parsed.required_skills, render=rendered)
    assert report.passed, report.as_dict()["errors"]
    assert not [w for w in report.as_dict()["warnings"] if w.startswith("ATS")]
    # Job text reached the model only as quoted data.
    assert "<job_description>" in llm.calls[0][0][1].content and "<bullets>" in llm.calls[0][0][1].content


def test_tampered_rewrite_is_caught_by_the_validator(setup, resume_doc, candidate=None):
    result, _, cand = setup
    doc = result.document.model_copy(deep=True)
    b = doc.experience[0].bullets[0]
    doc.experience[0].bullets[0] = b.model_copy(update={"text": b.text.replace("Kafka", "Kafka and Rust"), "source": b.text})
    assert not validate_facts(resume_doc, doc, Profile(), max_years=cand.years_including_internships).passed


def test_files_have_no_footer_table_or_odd_spaces(setup, tmp_path):
    result, _, _ = setup
    doc = result.document.model_copy(deep=True)
    doc.summary = doc.summary.replace(" ", " ", 3)  # as a parsed PDF master might carry
    render_resume(doc, tmp_path / "r.docx", tmp_path / "r.pdf")
    d = docx.Document(str(tmp_path / "r.docx"))
    assert not d.tables and not any(p.text for s in d.sections for p in s.footer.paragraphs + s.header.paragraphs)
    text = "\n".join(p.extract_text() for p in pypdf.PdfReader(tmp_path / "r.pdf").pages)
    assert " " not in text and "Page " not in text
    entry = doc.experience[0]
    assert any(entry.title in line and entry.date_text.split()[0] in line for line in text.splitlines())  # one line, title first

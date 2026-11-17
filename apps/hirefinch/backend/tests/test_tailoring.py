"""Resume tailoring, factual validation, DOCX/PDF generation and ATS checks."""

from __future__ import annotations

from datetime import date

import pytest
from agents_core.llm.testing import ScriptedLLM

from hirefinch.candidate import build_candidate
from hirefinch.domain import Bullet, Profile, RawJob, VerifiedSkill
from hirefinch.jobs.parser import parse_job
from hirefinch.llm_assist import rewrite_summary
from hirefinch.resume.parser import parse_resume
from hirefinch.resume.render import render_docx, render_pdf
from hirefinch.resume.tailor import tailor
from hirefinch.resume.validator import validate_facts, validate_files

AI_JD = """What you'll do
- Build AI agents with Google ADK and LLM orchestration
- Build RAG pipelines with vector search on GCP
Requirements
- 3+ years of experience in software engineering
- Python, Java, Spring Boot
- LLMs, RAG, AI agents
- Docker, Kubernetes
Nice to have
- LangGraph, Terraform"""


@pytest.fixture
def tailored(resume_doc):
    parsed = parse_job(RawJob(external_id="1", url="https://x.example/1", title="AI Agent Engineer", company="Acme",
                              description=AI_JD), AI_JD)
    candidate = build_candidate(resume_doc, Profile(), today=date(2026, 9, 1))
    return tailor(resume_doc, parsed, candidate, Profile(), role_family="ai_engineering", max_bullets_older_roles=2), parsed, candidate


def test_tailoring_reorders_without_inventing(resume_doc, tailored):
    result, _, _ = tailored
    doc = result.document
    assert doc.experience[0].bullets[0].id == "e1b2"  # the AI-agent bullet leads for an AI role
    assert [e.id for e in doc.experience] == ["e1", "e2", "e3"]  # chronology kept
    assert doc.contact.headline.startswith("Software Engineer · ")
    assert "LangGraph" in result.keyword_coverage["missing_not_in_profile"]
    assert "LangGraph" not in doc.full_text() and "Terraform" not in doc.full_text()
    assert len(doc.experience[1].bullets) == 2 and len(result.omitted_bullets) == 1
    assert result.diff.startswith("--- master")
    assert resume_doc.experience[0].bullets[0].id == "e1b1"  # master untouched


def test_verified_profile_skill_is_added_only_with_evidence(resume_doc):
    parsed = parse_job(RawJob(external_id="1", url="https://x.example/1", title="Platform Engineer", company="Acme",
                              description="Requirements\n- Terraform, Java"), "Requirements\n- Terraform, Java")
    profile = Profile(verified_extra_skills=[VerifiedSkill(name="Terraform", evidence="Used at Example Automation for infra")])
    candidate = build_candidate(resume_doc, profile)
    result = tailor(resume_doc, parsed, candidate, profile, role_family="java_backend")
    assert result.document.skills[-1].items == ["Terraform"]
    assert validate_facts(resume_doc, result.document, profile, max_years=4.2).passed


def test_validator_passes_honest_tailoring(resume_doc, tailored):
    result, _, candidate = tailored
    assert validate_facts(resume_doc, result.document, Profile(), max_years=candidate.years_including_internships).passed


@pytest.mark.parametrize("tamper,check", [
    (lambda d: d.experience[0].bullets.append(Bullet(id="e1b9", text="Led a team of 40 engineers.")), "bullets come from the master"),
    (lambda d: setattr(d.experience[1], "date_text", "January 2020 – February 2024"), "employment history unchanged"),
    (lambda d: setattr(d.experience[0], "company", "Google"), "employment history unchanged"),
    (lambda d: setattr(d, "summary", d.summary + " Cut costs by 75%."), "summary adds no new numbers"),
    (lambda d: setattr(d, "summary", "Software Engineer with 9 years of experience."), "experience claim within verified dates"),
    (lambda d: setattr(d, "summary", d.summary + " Expert in Rust and Terraform."), "summary adds no new technologies"),
    (lambda d: d.skills[0].items.append("Rust"), "skills come from the master or verified profile"),
    (lambda d: d.education.append("PhD, MIT"), "education unchanged"),
    (lambda d: setattr(d.contact, "email", "other@example.com"), "contact unchanged"),
])
def test_validator_catches_fabrication(resume_doc, tailored, tamper, check):
    result, _, _ = tailored
    doc = result.document.model_copy(deep=True)
    tamper(doc)
    report = validate_facts(resume_doc, doc, Profile(), max_years=4.2)
    assert not report.passed
    assert any(c.name == check and not c.passed for c in report.checks)


def test_generated_files_are_ats_readable(tmp_path, resume_doc, tailored):
    result, parsed, candidate = tailored
    docx_path, pdf_path = tmp_path / "r.docx", tmp_path / "r.pdf"
    render_docx(result.document, docx_path)
    render_pdf(result.document, pdf_path)
    report = validate_facts(resume_doc, result.document, Profile(), max_years=candidate.years_including_internships)
    validate_files(report, docx_path, pdf_path, result.document, parsed.required_skills + parsed.preferred_skills)
    out = report.as_dict()
    assert out["passed"], out["errors"]
    assert not out["warnings"], out["warnings"]
    # The generated PDF parses back into the same roles: proof the layout is machine-readable.
    _, reparsed = parse_resume(pdf_path.read_bytes(), "r.pdf")
    assert [(e.title, e.company) for e in reparsed.experience] == [(e.title, e.company) for e in result.document.experience]


async def test_llm_summary_is_only_a_proposal(resume_doc, tailored):
    result, parsed, candidate = tailored
    llm = ScriptedLLM(json_replies=[{"summary": "Software Engineer who cut cloud costs by 60% using Rust."}])
    proposal = await rewrite_summary(llm, resume_doc.summary, parsed, ["Python"])
    doc = result.document.model_copy(deep=True)
    doc.summary = proposal
    assert not validate_facts(resume_doc, doc, Profile(), max_years=candidate.years_including_internships).passed
    prompt = llm.calls[0][0][1].content
    assert "<job_description>" in prompt and "<master_summary>" in prompt

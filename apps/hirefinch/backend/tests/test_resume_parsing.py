"""Resume parsing (PDF and DOCX), experience totals and upload validation."""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

from hirefinch.candidate import build_candidate, experience_years
from hirefinch.domain import ExperienceEntry, Profile, VerifiedSkill
from hirefinch.resume.parser import Line, ResumeParseError, _Parser, _text_lines, parse_point, parse_resume


@pytest.mark.parametrize("fixture", ["resume_docx", "resume_pdf"])
def test_round_trip_keeps_structure(request, fixture, resume_doc):
    fmt, doc = parse_resume(request.getfixturevalue(fixture), f"cv.{fixture[-4:]}")
    assert fmt == fixture[-4:].replace("_", "")
    assert doc.contact.name == "RIYA SHARMA"
    assert doc.contact.email == "riya.sharma@example.com"
    assert [e.title for e in doc.experience] == [e.title for e in resume_doc.experience]
    assert [e.company for e in doc.experience] == [e.company for e in resume_doc.experience]
    assert doc.experience[0].is_current and doc.experience[0].start == date(2024, 3, 1)
    assert doc.experience[1].end == date(2024, 2, 1)
    assert doc.experience[2].is_internship
    assert [len(e.bullets) for e in doc.experience] == [4, 3, 1]
    assert [p.name for p in doc.projects] == [p.name for p in resume_doc.projects]
    assert doc.projects[0].technologies == ["Python", "Google ADK", "Vertex AI", "RAG"]
    assert {g.name for g in doc.skills} == {g.name for g in resume_doc.skills}
    assert doc.education == resume_doc.education
    assert doc.warnings == []


def test_wrapped_pdf_lines_join_the_previous_bullet():
    text = "\n".join([
        "JANE DOE", "jane@example.com | +91 98000 00000",
        "PROFESSIONAL EXPERIENCE",
        "Software Engineer", "Acme Corp", "Bengaluru, India · February 2024 – Present",
        "\x7f  Built a provider-agnostic orchestration layer integrating OpenAI and Gemini with",
        " dynamic model selection and validation.",
        "\x7f  Engineered integrations connecting agents with the platform (Google",
        "ADK) to external systems.",
        "Associate Engineer", "Beta Ltd", "Pune · Nov 2022 – Jan 2024",
        "• Wrote REST APIs.",
    ])
    doc = _Parser(_text_lines(text)).run()
    assert [e.title for e in doc.experience] == ["Software Engineer", "Associate Engineer"]
    first = doc.experience[0]
    assert first.company == "Acme Corp" and first.location == "Bengaluru, India"
    assert len(first.bullets) == 2
    assert first.bullets[0].text.endswith("dynamic model selection and validation.")
    assert first.bullets[1].text.endswith("(Google ADK) to external systems.")
    assert doc.experience[1].start == date(2022, 11, 1) and doc.experience[1].end == date(2024, 1, 1)


def test_tab_separated_title_and_dates_docx_style():
    lines = [Line("JOHN ROE"), Line("john@example.com"), Line("EXPERIENCE"),
             Line("Software Engineer  |  Feb 2024 – Present"), Line("Acme Corp | Bengaluru, India"),
             Line("Did things.", bullet=True)]
    doc = _Parser(lines).run()
    assert doc.experience[0].title == "Software Engineer"
    assert doc.experience[0].company == "Acme Corp"
    assert doc.experience[0].location == "Bengaluru, India"
    assert doc.experience[0].is_current


@pytest.mark.parametrize("text,expected", [("Feb 2024", date(2024, 2, 1)), ("September 2022", date(2022, 9, 1)),
                                           ("03/2021", date(2021, 3, 1)), ("2019", date(2019, 1, 1)), ("13/2020", None)])
def test_date_points(text, expected):
    assert parse_point(text) == expected


def test_experience_years_merges_overlaps_and_excludes_internships():
    entries = [
        ExperienceEntry(id="a", title="Eng", company="A", start=date(2022, 1, 1), end=date(2022, 12, 1)),
        ExperienceEntry(id="b", title="Eng", company="B", start=date(2022, 7, 1), end=date(2023, 12, 1)),
        ExperienceEntry(id="c", title="Intern", company="C", start=date(2021, 1, 1), end=date(2021, 6, 1), is_internship=True),
    ]
    assert experience_years(entries, include_internships=False) == 2.0
    assert experience_years(entries, include_internships=True) == 2.5


def test_candidate_skills_need_evidence(resume_doc):
    profile = Profile(verified_extra_skills=[VerifiedSkill(name="Terraform", evidence="Certificate of course XYZ")])
    candidate = build_candidate(resume_doc, profile, today=date(2026, 9, 1))
    assert candidate.has("Kafka") and candidate.has("Google ADK") and candidate.has("Terraform")
    assert not candidate.has("LangGraph")
    assert candidate.years_experience == 4.1  # Sep 2022 – Sep 2026 inclusive, without the internship
    assert candidate.years_including_internships == 4.3
    assert candidate.current_company == "Example Automation Pvt. Ltd."


def test_rejects_unsupported_and_malformed_files():
    with pytest.raises(ResumeParseError):
        parse_resume(b"just text", "resume.txt")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("hello.txt", "not a docx")
    with pytest.raises(ResumeParseError):
        parse_resume(buffer.getvalue(), "resume.docx")
    with pytest.raises(ResumeParseError):
        parse_resume(b"%PDF-1.4 broken", "resume.pdf")
    with pytest.raises(ResumeParseError):
        parse_resume(b"%PDF-" + b"0" * (6 * 1024 * 1024), "big.pdf")

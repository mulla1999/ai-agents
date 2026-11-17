"""Rendered-layout regression tests: pagination, typography limits, DOCX/PDF parity, reading order.

The sweep test moves the page break across every position in the experience and project
sections; at each one no heading or role title may be stranded and no content may go missing.
"""

from __future__ import annotations

from pathlib import Path

import docx
import pypdf
import pytest

from hirefinch.domain import Bullet, ProjectEntry, ResumeDocument, SkillGroup
from hirefinch.resume.layout import inspect_docx, inspect_pdf
from hirefinch.resume.render import plain, render_resume
from hirefinch.resume.style import COMPACT, STANDARD, ResumeStyle

LONG = ("Designed and operated a multi-region event-driven platform on Kafka and Kubernetes with retry, idempotency "
        "and dead-letter handling, coordinating schema evolution across teams and documenting every runbook")


def _with_bullets(doc: ResumeDocument, extra: int, text: str = LONG) -> ResumeDocument:
    doc = doc.model_copy(deep=True)
    entry = doc.experience[0]
    entry.bullets += [Bullet(id=f"x{i}", text=f"{text} (item {i}).") for i in range(extra)]
    return doc


def _check(tmp_path: Path, doc: ResumeDocument, name: str = "r"):
    docx_path, pdf_path = tmp_path / f"{name}.docx", tmp_path / f"{name}.pdf"
    result = render_resume(doc, docx_path, pdf_path)
    pdf_text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(pdf_path).pages)
    checks = inspect_pdf(pdf_path, doc, result.style) + inspect_docx(docx_path, doc, result.style, pdf_text)
    failures = [f"{n}: {d}" for n, ok, d, sev in checks if not ok and sev == "error"]
    return result, failures, pdf_text, docx_path


def test_short_resume_is_one_clean_page(tmp_path, resume_doc):
    result, failures, text, _ = _check(tmp_path, resume_doc)
    assert not failures, failures
    assert result.pages == 1 and result.style.name == "standard" and not result.continued
    assert text.strip().splitlines()[0].strip() == "RIYA SHARMA"  # name first
    assert "Page" not in text and text.upper().count("RIYA SHARMA") == 1  # no footer for an ATS to misread


def test_long_resume_continues_cleanly(tmp_path, resume_doc):
    doc = _with_bullets(resume_doc, 14)
    result, failures, text, _ = _check(tmp_path, doc)
    assert not failures, failures
    assert result.pages >= 2
    # No repeated "(continued)" title or page footer: an ATS could read either as another job.
    assert "(continued)" not in text and "Page 2 of" not in text


def test_extensive_skills_and_long_projects(tmp_path, resume_doc):
    doc = resume_doc.model_copy(deep=True)
    doc.skills.append(SkillGroup(name="Other Tools", items=[f"Tool {i}" for i in range(60)]))
    doc.projects += [ProjectEntry(id=f"px{i}", name=f"Platform Project {i} — Distributed Workflow Engine",
                                  subtitle="Company product", technologies=["Java", "Kafka", "Kubernetes", "AWS", "React"],
                                  bullets=[Bullet(id=f"px{i}b", text=LONG + " " + LONG + ".")]) for i in range(6)]
    result, failures, _, _ = _check(tmp_path, doc)
    assert not failures, failures
    assert result.pages >= 2


@pytest.mark.parametrize("extra", range(0, 22, 3))
def test_page_break_sweep(tmp_path, resume_doc, extra):
    """Each step pushes later content further down, so the break lands on a different block."""
    result, failures, _, _ = _check(tmp_path, _with_bullets(resume_doc, extra, LONG[:120]), f"s{extra}")
    assert not failures, (extra, result.pages, failures)


def test_compact_variant_is_used_only_when_it_saves_a_page(tmp_path, resume_doc):
    # Add bullets until the standard style spills onto a third page.
    for extra in range(8, 40, 2):
        doc = _with_bullets(resume_doc, extra, LONG[:150])
        result = render_resume(doc, tmp_path / "c.docx", tmp_path / "c.pdf")
        if result.style.name == "compact":
            assert result.pages <= 2
            return
    pytest.fail("compact variant was never selected")


def test_both_formats_share_the_style(tmp_path, resume_doc):
    result, _, _, docx_path = _check(tmp_path, resume_doc)
    document = docx.Document(str(docx_path))
    normal = document.styles["Normal"]
    assert normal.font.name == "Arial" and normal.font.size.pt == result.style.body_pt
    assert normal.paragraph_format.line_spacing.pt == pytest.approx(result.style.leading(result.style.body_pt), abs=0.05)
    section = document.sections[0]
    assert abs(section.left_margin.inches - result.style.margin_in) < 0.01
    heading = next(p for p in document.paragraphs if p.text == "PROFESSIONAL EXPERIENCE")
    assert heading.paragraph_format.keep_with_next and heading.paragraph_format.space_before.pt == result.style.heading_space_before_pt
    role = next(p for p in document.paragraphs if p.text.startswith("Software Engineer\t"))
    assert role.paragraph_format.keep_with_next


def test_style_limits_are_enforced():
    with pytest.raises(ValueError):
        ResumeStyle(body_pt=8.5)
    with pytest.raises(ValueError):
        ResumeStyle(name_pt=26)
    for style in (STANDARD, COMPACT):
        assert 9.5 <= style.body_pt <= 10.5 and 0.65 <= style.margin_in <= 0.75
        assert style.bullet_space_after_pt >= 3 and style.heading_space_before_pt >= 10


def test_plain_spaces_only():
    assert plain("Spring\u00a0Boot and\u2009Kafka\u200b") == "Spring Boot and Kafka"


def test_layout_checks_catch_missing_content(tmp_path, resume_doc):
    _, failures, _, _ = _check(tmp_path, resume_doc)
    assert not failures
    rendered_without = resume_doc.model_copy(deep=True)
    rendered_without.experience[0].bullets = rendered_without.experience[0].bullets[:1]
    render_resume(rendered_without, tmp_path / "m.docx", tmp_path / "m.pdf")
    text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(tmp_path / "m.pdf").pages)
    # Validate the rendered files against the fuller document: the dropped bullets must be reported.
    checks = inspect_pdf(tmp_path / "m.pdf", resume_doc, STANDARD) + inspect_docx(tmp_path / "m.docx", resume_doc, STANDARD, text)
    failed = {n for n, ok, _, _ in checks if not ok}
    assert {"all content present in PDF text", "all content present in DOCX"} <= failed


def test_stranded_heading_check_detects_a_bad_break(tmp_path, resume_doc):
    """A hand-made PDF whose first page ends with a role title must fail the check."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from hirefinch.resume.render import _pdf_fonts

    regular, _, _ = _pdf_fonts()
    path = tmp_path / "bad.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    lines = ["RIYA SHARMA", "PROFESSIONAL SUMMARY", resume_doc.summary[:80], "PROFESSIONAL EXPERIENCE", "Software Engineer"]
    for page_lines in (lines, ["Example Automation Pvt. Ltd. | Pune, India", *(b.text for b in resume_doc.all_bullets())]):
        c.setFont(regular, 10)
        y = 780
        for line in page_lines:
            c.drawString(60, y, line[:95])
            y -= 14
        c.showPage()
    c.save()
    checks = {n: (ok, d) for n, ok, d, _ in inspect_pdf(path, resume_doc, STANDARD)}
    ok, detail = checks["no stranded headings at page ends"]
    assert not ok and "software engineer" in detail

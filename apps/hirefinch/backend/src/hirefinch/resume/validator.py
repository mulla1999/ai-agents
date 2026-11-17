"""Resume validation: factual consistency against the master, then formatting and ATS readability
of the generated files. A tailored resume that fails a factual check is never used for an
application.
"""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..domain import Profile, ResumeDocument
from ..skills import extract_skills
from .layout import inspect_docx, inspect_pdf
from .render import RenderResult
from .style import STANDARD, ResumeStyle

STANDARD_HEADINGS = ("PROFESSIONAL SUMMARY", "TECHNICAL SKILLS", "PROFESSIONAL EXPERIENCE", "EDUCATION")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?\s*(?:%|\+|x\b|k\b|m\b)?", re.IGNORECASE)
_YEARS_CLAIM = re.compile(r"(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)", re.IGNORECASE)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    severity: str = "error"  # error | warning


@dataclass
class ValidationReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.severity == "error")

    def add(self, name: str, passed: bool, detail: str = "", severity: str = "error") -> None:
        self.checks.append(Check(name, passed, detail, severity))

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "errors": [c.detail or c.name for c in self.checks if not c.passed and c.severity == "error"],
            "warnings": [c.detail or c.name for c in self.checks if not c.passed and c.severity == "warning"],
            "checks": [asdict(c) for c in self.checks],
        }


def numbers_in(text: str) -> set[str]:
    return {re.sub(r"\s+", "", m.group(0)).lower() for m in _NUMBER.finditer(text)}


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]*")
_STOP = frozenset("the and for with from into that this using used use was were has have had are our its their a an to of in on "
                  "by at as or via across over under within while which also more than".split())
# Words that claim more responsibility or seniority than a bullet may have stated.
_INFLATION = ("led", "lead", "leading", "managed", "managing", "mentored", "owned", "architected", "spearheaded", "headed",
              "directed", "supervised", "expert", "world-class", "best-in-class", "rockstar", "guru", "visionary")
_FIRST_PERSON = re.compile(r"\b(i|me|my|we|our|us)\b", re.IGNORECASE)


def _stem(word: str) -> str:
    w = word.lower().rstrip(".")
    for suffix in ("ing", "ed", "es", "s"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def rewrite_problem(original: str, rewritten: str, facts: str = "", *, draft: bool = False, shorten: bool = False) -> str | None:
    """Why a reworded bullet cannot replace its master bullet, or None when it keeps to the facts.

    A rewrite may change wording, order and emphasis. It must keep every number and technology,
    add none, not claim more responsibility, and stay recognisably the same achievement.

    ``facts`` is detail the person typed themselves (Resume Builder, "Make it measurable"): its numbers,
    technologies and words may be used too, but don't have to be. ``draft`` (a bullet someone is still
    writing, often a few words) lets the rewrite grow longer, and ``shorten`` (cutting an overlong bullet)
    lets it shrink further; every other check still applies."""
    new = " ".join(rewritten.split())
    source = f"{original} {facts}".strip()
    if not new or new == original:
        return "unchanged"
    base = len(source) if facts else len(original)
    longest = max(2.5 * base, base + 120) if draft else max(1.35 * base, base + 40)
    if not (0.3 if shorten else 0.6) * len(original) <= len(new) <= longest or len(new) > 320:
        return "length changed too much"
    if facts:
        if not numbers_in(original) <= numbers_in(new) or not numbers_in(new) <= numbers_in(source):
            return "numbers added or dropped"
    elif numbers_in(new) != numbers_in(original):
        return "numbers added or dropped"
    old_skills, new_skills = set(extract_skills(original)), set(extract_skills(new))
    allowed = set(extract_skills(source))
    if new_skills - allowed:
        return "adds technologies: " + ", ".join(sorted(new_skills - allowed))
    if old_skills - new_skills:
        return "drops technologies: " + ", ".join(sorted(old_skills - new_skills))
    # Words can carry punctuation from the sentence ("Manager." at the end): compare them without it.
    old_words = {w.rstrip(".-").lower() for w in _WORD.findall(source)}
    words = [w.rstrip(".-") or w for w in _WORD.findall(new)]
    if inflated := [w for w in words if w.lower() in _INFLATION and w.lower() not in old_words]:
        return f"claims more than the original ({inflated[0]})"
    if _FIRST_PERSON.search(new) and not _FIRST_PERSON.search(original):
        return "first person"
    names = [w for w in words[1:] if w[0].isupper() and w.lower() not in old_words and w.upper() != w]
    if names:
        return f"adds a name not in the original ({names[0]})"
    content = lambda text: {_stem(w) for w in _WORD.findall(text) if len(w) > 3 and w.lower() not in _STOP}  # noqa: E731
    a, b = content(source), content(new)
    if draft:  # growing a short draft adds words; it must still keep most of what the person wrote
        mine = content(original)
        if mine and len(mine & b) / len(mine) < 0.5:
            return "no longer the same achievement"
    elif a and len(a & b) / len(a | b) < 0.3:
        return "no longer the same achievement"
    return None


def validate_facts(
    master: ResumeDocument, tailored: ResumeDocument, profile: Profile, *, max_years: float
) -> ValidationReport:
    report = ValidationReport()
    mc, tc = master.contact, tailored.contact
    report.add("contact unchanged", (mc.name, mc.email, mc.phone) == (tc.name, tc.email, tc.phone),
               "name, email or phone differs from the master resume")

    def roles(doc: ResumeDocument) -> list[tuple]:
        return [(e.title, e.company, e.date_text, e.location, e.start, e.end, e.is_current) for e in doc.experience]

    report.add("employment history unchanged", roles(master) == roles(tailored),
               "an employer, title, location or date differs from the master, or a role was removed or reordered")
    report.add("education unchanged", master.education == tailored.education, "education differs from the master")
    report.add("certifications unchanged", master.certifications == tailored.certifications,
               "certifications differ from the master")

    master_bullets = {e.id: {b.text for b in e.bullets} for e in master.experience}
    master_bullets.update({p.id: {b.text for b in p.bullets} for p in master.projects})
    def foreign(entry_id: str, b) -> bool:  # noqa: ANN001
        allowed = master_bullets.get(entry_id, set())
        if b.text in allowed:
            return False
        # A reworded bullet is accepted only against its own master bullet, and only if it keeps the facts.
        return not (b.source in allowed and rewrite_problem(b.source, b.text) is None)

    bad = [b.text[:80] for e in tailored.experience for b in e.bullets if foreign(e.id, b)]
    bad += [b.text[:80] for p in tailored.projects for b in p.bullets if foreign(p.id, b)]
    report.add("bullets come from the master", not bad, "bullets not in the master: " + "; ".join(bad[:3]))

    master_projects = {p.id: (p.name, p.subtitle, tuple(p.technologies)) for p in master.projects}
    changed = [p.name for p in tailored.projects if master_projects.get(p.id) != (p.name, p.subtitle, tuple(p.technologies))]
    report.add("projects unchanged", not changed, "project details differ: " + ", ".join(changed))

    master_text = master.full_text()
    verified_extra = {s for x in profile.verified_extra_skills for s in (extract_skills(x.name) or [x.name])}
    allowed_skills = set(extract_skills(master_text)) | verified_extra
    master_items = {i for g in master.skills for i in g.items} | {x.name for x in profile.verified_extra_skills}
    new_items = [i for g in tailored.skills for i in g.items if i not in master_items]
    report.add("skills come from the master or verified profile", not new_items, "unverified skills: " + ", ".join(new_items))

    headline_skills = set(extract_skills(tailored.contact.headline or "")) - allowed_skills
    report.add("headline skills verified", not headline_skills, "headline names unverified skills: "
               + ", ".join(sorted(headline_skills)))

    summary_new_numbers = numbers_in(tailored.summary) - numbers_in(master_text)
    report.add("summary adds no new numbers", not summary_new_numbers,
               "summary contains figures not in the master: " + ", ".join(sorted(summary_new_numbers)))
    summary_new_skills = set(extract_skills(tailored.summary)) - allowed_skills
    report.add("summary adds no new technologies", not summary_new_skills,
               "summary names technologies not in the master: " + ", ".join(sorted(summary_new_skills)))
    claims = [float(m.group(1)) for m in _YEARS_CLAIM.finditer(tailored.summary + " " + (tailored.contact.headline or ""))]
    over = [c for c in claims if c > max_years + 0.25]
    report.add("experience claim within verified dates", not over,
               f"claims {max(over) if over else 0:g} years but your resume dates support {max_years:g}")
    master_count = sum(1 for e in master.experience for _ in e.bullets)
    tailored_count = sum(1 for e in tailored.experience for _ in e.bullets)
    report.add("most experience retained", master_count == 0 or tailored_count / master_count >= 0.6,
               f"only {tailored_count} of {master_count} experience bullets kept", "warning")
    return report


def validate_files(report: ValidationReport, docx_path: Path, pdf_path: Path, tailored: ResumeDocument,
                   wanted_skills: list[str], style: ResumeStyle = STANDARD,
                   render: RenderResult | None = None) -> ValidationReport:
    import docx
    import pypdf

    name = tailored.contact.name
    docx_text = "\n".join(p.text for p in docx.Document(str(docx_path)).paragraphs)
    reader = pypdf.PdfReader(io.BytesIO(pdf_path.read_bytes()))
    pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    flat_pdf = re.sub(r"\s+", " ", pdf_text).upper()

    report.add("DOCX readable", name in docx_text and all(h in docx_text for h in STANDARD_HEADINGS if _has(tailored, h)),
               "DOCX text is missing the name or a standard heading")
    report.add("PDF text selectable", bool(pdf_text.strip()) and name.upper() in flat_pdf,
               "PDF has no extractable text or the name is not readable")
    missing_headings = [h for h in STANDARD_HEADINGS if _has(tailored, h) and h not in flat_pdf]
    report.add("standard section headings", not missing_headings, "missing headings in PDF: " + ", ".join(missing_headings))
    if tailored.contact.email:
        report.add("contact email in PDF", tailored.contact.email.lower() in pdf_text.lower().replace(" ", ""),
                   "email address not extractable from the PDF")
    for name_, passed, detail, severity in inspect_pdf(pdf_path, tailored, style) + inspect_docx(
            docx_path, tailored, style, pdf_text):
        report.add(name_, passed, detail, severity)
    if render is not None:
        if render.continued:
            report.add("entries continued across pages", True, "continued: " + "; ".join(render.continued), "warning")
        report.add("last page well filled", render.pages == 1 or render.last_page_fill >= 0.15,
                   f"the last page is only {render.last_page_fill:.0%} full: check the preview", "warning")
    _ats_checks(report, docx_path, pdf_text, tailored)
    words = len(docx_text.split())
    report.add("concise", words <= 1100, f"{words} words; consider trimming below 1,100", "warning")
    styles = {_date_style(e.date_text) for e in tailored.experience if e.date_text}
    report.add("consistent date format", len(styles) <= 1, "experience dates use mixed formats", "warning")
    empty = [s for s, v in (("summary", tailored.summary), ("skills", tailored.skills), ("experience", tailored.experience)) if not v]
    report.add("no empty sections", not empty, "empty sections: " + ", ".join(empty), "warning")
    if wanted_skills:
        present = set(extract_skills(pdf_text))
        coverage = sum(1 for s in wanted_skills if s in present) / len(wanted_skills)
        report.add("keyword coverage", coverage >= 0.5, f"{coverage:.0%} of the job's skills appear in the PDF", "warning")
    return report


_ODD = re.compile("[\u00a0\u2000-\u200b\u202f\u205f\u2060\u3000\ufeff]")


def _ats_checks(report: ValidationReport, docx_path: Path, pdf_text: str, doc: ResumeDocument) -> None:
    """What applicant tracking systems most often misread, checked on the generated files."""
    import docx

    d = docx.Document(str(docx_path))
    repeated = [p.text for sec in d.sections for part in (sec.header, sec.footer) for p in part.paragraphs if p.text.strip()]
    report.add("ATS: no header or footer", not repeated, "header/footer text: " + "; ".join(repeated[:2]))
    xml = d.element.xml
    report.add("ATS: no tables, text boxes or images", not d.tables and "txbxContent" not in xml and "<w:drawing" not in xml,
               "the DOCX contains a table, text box or image")
    report.add("ATS: plain spaces", not _ODD.search(pdf_text) and not _ODD.search("\n".join(p.text for p in d.paragraphs)),
               "no-break or zero-width spaces can hide keywords from an ATS")
    lines = [" ".join(line.split()) for line in pdf_text.splitlines()]
    unreadable = [e.title for e in doc.experience if e.date_text and not any(
        e.title[:25] in line and (e.date_text.split()[0] in line or any(e.date_text.split()[0] in nxt for nxt in lines[i + 1:i + 2]))
        for i, line in enumerate(lines))]
    report.add("ATS: role titles read with their dates", not unreadable,
               "title and dates not next to each other in the PDF text: " + ", ".join(unreadable[:3]), "warning")
    name = doc.contact.name.strip().upper()
    count = re.sub(r"\s+", " ", pdf_text).upper().count(name) if name else 1
    report.add("ATS: name appears once", count <= 1, f"the name appears {count} times (repeated header or footer?)", "warning")


def _has(doc: ResumeDocument, heading: str) -> bool:
    return {
        "PROFESSIONAL SUMMARY": bool(doc.summary),
        "TECHNICAL SKILLS": bool(doc.skills),
        "PROFESSIONAL EXPERIENCE": bool(doc.experience),
        "EDUCATION": bool(doc.education),
    }.get(heading, True)


def _date_style(text: str) -> str:
    if re.search(r"\d{1,2}/\d{4}", text):
        return "numeric"
    if re.search(r"[A-Za-z]{4,}\s+\d{4}", text) and not re.search(r"\b[A-Za-z]{3}\s+\d{4}", text):
        return "full-month"
    return "short-month" if re.search(r"\b[A-Za-z]{3}\s+\d{4}", text) else "year"

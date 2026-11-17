"""ATS parse test: can a machine read this resume back correctly?

There is no standard "ATS score": Workday, Greenhouse, Lever and iCIMS parse a resume into fields, and
recruiters then search those fields. What breaks applications is a parser misreading the file
(tables, columns, headers/footers, image-only PDFs, odd headings). So this test measures exactly that:
it renders the real PDF and Word files, runs the file checks used for every tailored resume, then
parses both files back and compares every fact with what was written. The result is measured, not
estimated: "34 of 34 facts read back correctly".

Our parser stands in for a commercial one. It follows the same rules (text layer, reading order,
standard headings), so a resume that reads back cleanly here has none of the known failure causes; it
cannot promise how one particular vendor's parser will behave.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from ..domain import ResumeDocument
from ..skills import extract_skills
from .parser import ResumeParseError, parse_resume
from .render import render_resume
from .validator import ValidationReport, validate_files

_WORD = re.compile(r"[a-z0-9+#]+")


def _norm(text: str | None) -> str:
    return " ".join((text or "").lower().split())


def _digits(text: str | None) -> str:
    return re.sub(r"\D", "", text or "")[-10:]


def _link(text: str) -> str:
    return re.sub(r"^(https?://)?(www\.)?", "", text.strip().lower()).rstrip("/")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _same_text(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    return bool(wa) and len(wa & wb) / len(wa) >= 0.9


def compare(source: ResumeDocument, read: ResumeDocument) -> list[dict]:
    """Every fact in ``source`` and whether ``read`` (the parsed file) got it right."""
    facts: list[dict] = []

    def fact(label: str, ok: bool, detail: str = "") -> None:
        facts.append({"fact": label, "ok": bool(ok), "detail": "" if ok else detail})

    c, r = source.contact, read.contact
    if c.name:
        fact("Name", _norm(c.name) == _norm(r.name), f"read as “{r.name or 'nothing'}”")
    if c.email:
        fact("Email", _norm(c.email) == _norm(r.email), f"read as “{r.email or 'nothing'}”")
    if c.phone:
        fact("Phone", _digits(c.phone) == _digits(r.phone), f"read as “{r.phone or 'nothing'}”")
    read_links = {_link(x) for x in r.links}
    for link in c.links:
        fact(f"Link {link}", _link(link) in read_links, "not found")

    # Pair each written role with the read-back role that matches it best (title, company and dates), best
    # pairs first, so one lost role doesn't make every later one look wrong.
    def overlap(a, b) -> int:  # noqa: ANN001
        return len(_words(f"{a.title} {a.company} {a.date_text}") & _words(f"{b.title} {b.company} {b.date_text}"))

    pairs = sorted(((overlap(s, r), i, j) for i, s in enumerate(source.experience) for j, r in enumerate(read.experience)), reverse=True)
    paired: dict[int, int] = {}
    for score, i, j in pairs:
        if score and i not in paired and j not in paired.values() and _words(source.experience[i].title) & _words(read.experience[j].title):
            paired[i] = j
    for i, entry in enumerate(source.experience):
        got = read.experience[paired[i]] if i in paired else None
        role = f"{entry.title} at {entry.company}"
        fact(f"{role}: job title", got is not None and _norm(entry.title) in _norm(got.title),
             f"read as “{got.title}”" if got else "role not found")
        if entry.company:
            fact(f"{role}: company", got is not None and _norm(entry.company) in _norm(got.company),
                 f"read as “{got.company}”" if got else "role not found")
        if entry.start or entry.date_text:
            same = got is not None and (
                (entry.start is not None and got.start is not None and (entry.start.year, entry.start.month) == (got.start.year, got.start.month))
                or (entry.start is None and _norm(entry.date_text) == _norm(got.date_text)))
            fact(f"{role}: dates", same and (got is not None and got.is_current == entry.is_current),
                 f"read as “{got.date_text}”" if got else "role not found")
        read_bullets = [b.text for b in got.bullets] if got else []
        for b in entry.bullets:
            fact(f"{role}: bullet “{b.text[:60]}{'…' if len(b.text) > 60 else ''}”",
                 any(_same_text(b.text, x) for x in read_bullets), "missing or garbled")

    for project in source.projects:
        got = next((p for p in read.projects if _norm(project.name) in _norm(p.name)), None)
        fact(f"Project {project.name}", got is not None, "project not found")

    wanted = {_norm(i) for g in source.skills for i in g.items}
    found = {_norm(i) for g in read.skills for i in g.items}
    for skill in sorted(wanted):
        fact(f"Skill {skill}", skill in found, "not read from the Skills section")

    read_education = " ".join(read.education)
    for line in source.education:
        fact(f"Education “{line[:50]}”", _same_text(line, read_education), "not found")
    return facts


def run(doc: ResumeDocument, wanted_required: list[str] | None = None, wanted_preferred: list[str] | None = None) -> dict:
    """Render, check the files, read both back, and (with a job's skills) measure keyword coverage."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf, docx = Path(tmp) / "resume.pdf", Path(tmp) / "resume.docx"
        render = render_resume(doc, docx, pdf)
        report = validate_files(ValidationReport(), docx, pdf, doc, [], style=render.style, render=render)
        files = {}
        for label, path in (("PDF", pdf), ("Word", docx)):
            try:
                _, read = parse_resume(path.read_bytes(), path.name)
                facts = compare(doc, read)
            except ResumeParseError as exc:
                facts = [{"fact": "Any text", "ok": False, "detail": str(exc)}]
            files[label] = {"read": sum(f["ok"] for f in facts), "total": len(facts),
                            "misses": [f for f in facts if not f["ok"]][:20]}
        import pypdf  # local: heavy import, only needed here

        text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(str(pdf)).pages)

    checks = [{"check": c.name, "ok": c.passed, "detail": c.detail if not c.passed else "", "severity": c.severity}
              for c in report.checks if c.name.startswith("ATS:") or c.severity == "error"]
    read_total = sum(f["total"] for f in files.values()) or 1
    read_ok = sum(f["read"] for f in files.values())
    blocking = [c for c in checks if not c["ok"] and c["severity"] == "error"]
    # The readability score is the share of facts read back from both files; a failed file check (e.g. text
    # in a header) is something many ATS parsers drop, so it caps the score.
    score = round(100 * read_ok / read_total)
    if blocking:
        score = min(score, 60)
    out = {"readability": {"score": score, "files": files, "checks": checks, "pages": render.pages}}
    if wanted_required or wanted_preferred:
        present = set(extract_skills(text))
        req, pref = wanted_required or [], wanted_preferred or []
        out["keywords"] = {"required_found": [s for s in req if s in present], "required_missing": [s for s in req if s not in present],
                           "preferred_found": [s for s in pref if s in present], "preferred_missing": [s for s in pref if s not in present]}
    return out

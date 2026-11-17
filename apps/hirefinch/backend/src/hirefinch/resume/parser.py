"""Parse a PDF or DOCX resume into a ``ResumeDocument``.

Both formats are first reduced to lines (bullets marked), then one section parser handles them.
The parse is heuristic, so it reports warnings and you can correct it in the UI; the corrected
structure, not the guess, then becomes the source of truth for tailoring.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date

from ..domain import Bullet, Contact, ExperienceEntry, ExtraSection, ProjectEntry, ResumeDocument, SkillGroup
from ..text import clean_whitespace

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
_MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024


class ResumeParseError(ValueError):
    pass


@dataclass
class Line:
    text: str
    bullet: bool = False


# ---------------------------------------------------------------- file → lines

_BULLET_CHARS = "•●▪◦■□➢►–-*\x7f"
_BULLET_RE = re.compile(rf"^\s*[{re.escape(_BULLET_CHARS)}]\s+")
# Only unambiguous page furniture: "... Page 2 of 3", a bare "Page 2", or a "(continued)" line.
_PAGE_FURNITURE = re.compile(r"\bpage\s+\d+\s+of\s+\d+\s*$|^\s*page\s+\d+\s*$|\(continued\)\s*$", re.IGNORECASE)


def detect_format(data: bytes, filename: str) -> str:
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "word/document.xml" in zf.namelist():
                    if sum(i.file_size for i in zf.infolist()) > _MAX_DOCX_UNCOMPRESSED:
                        raise ResumeParseError("DOCX expands to an unreasonable size")
                    return "docx"
        except zipfile.BadZipFile as exc:
            raise ResumeParseError("file is not a valid DOCX") from exc
    raise ResumeParseError(f"{filename}: only PDF and DOCX resumes are supported")


def pdf_lines(data: bytes) -> list[Line]:
    import pypdf

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ResumeParseError("encrypted PDFs are not supported")
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:10])
    except pypdf.errors.PdfReadError as exc:
        raise ResumeParseError(f"could not read PDF: {exc}") from exc
    return _text_lines(text)


def _text_lines(text: str) -> list[Line]:
    out: list[Line] = []
    orphan_bullet = False
    for raw in text.replace("\r", "").split("\n"):
        if not raw.strip():
            continue
        if _PAGE_FURNITURE.search(raw):  # page footers and "(continued)" lines are not content
            continue
        if raw.strip() in _BULLET_CHARS:  # some PDF generators put the glyph on its own line
            orphan_bullet = True
            continue
        bullet = bool(_BULLET_RE.match(raw)) or orphan_bullet
        orphan_bullet = False
        line = _BULLET_RE.sub("", raw) if bullet else raw
        line = clean_whitespace(line)
        if line:
            out.append(Line(line, bullet))
    return out


def docx_lines(data: bytes) -> list[Line]:
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # python-docx raises several unrelated types for corrupt files
        raise ResumeParseError(f"could not read DOCX: {exc}") from exc
    out: list[Line] = []
    for paragraph in document.paragraphs:
        text = paragraph.text
        if not text.strip():
            continue
        ppr = paragraph._p.pPr
        numbered = ppr is not None and ppr.numPr is not None
        style = (paragraph.style.name if paragraph.style is not None else "") or ""
        bullet = numbered or "list" in style.lower() or bool(_BULLET_RE.match(text))
        text = _BULLET_RE.sub("", text) if _BULLET_RE.match(text) else text
        # Tabs separate a title from its dates; keep them visible as a separator.
        out.append(Line(clean_whitespace(text.replace("\t", "  |  ")), bullet))
    for table in document.tables:  # rarely used for resumes, but do not lose the text
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                out.append(Line(clean_whitespace(" | ".join(dict.fromkeys(cells)))))
    return out


def extract_lines(data: bytes, filename: str) -> tuple[str, list[Line]]:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ResumeParseError("resume files must be 5 MB or smaller")
    fmt = detect_format(data, filename)
    return fmt, pdf_lines(data) if fmt == "pdf" else docx_lines(data)


def resume_text(data: bytes, filename: str) -> str:
    return "\n".join(line.text for line in extract_lines(data, filename)[1])


# ---------------------------------------------------------------- sections

_HEADINGS = {
    "summary": ("summary", "professional summary", "profile", "profile summary", "about", "about me", "objective",
                "career objective", "career summary"),
    "skills": ("skills", "technical skills", "core skills", "key skills", "core competencies", "technical expertise",
               "skills & tools", "technologies"),
    "experience": ("experience", "professional experience", "work experience", "employment history", "employment",
                   "work history", "career history"),
    "projects": ("projects", "key projects", "personal projects", "selected projects", "notable projects"),
    "education": ("education", "academic background", "education & training", "education and training",
                  "academics", "qualifications"),
    "certifications": ("certifications", "certificates", "licenses & certifications", "certifications & training",
                       "training & certifications"),
}
_HEADING_LOOKUP = {name: section for section, names in _HEADINGS.items() for name in names}
_OTHER_HEADINGS = ("achievements", "awards", "publications", "languages", "interests", "volunteering",
                   "honors & awards", "additional information", "hobbies")


# Headings people word their own way ("CORE TECHNICAL SKILLS", "RELEVANT WORK EXPERIENCE:"), recognised by
# their last word. A job title such as "Head of Customer Experience" or a project called "Order History"
# must not start a section, so this needs ALL CAPS or a trailing ":"; only skills-style endings, which
# job titles never use, are also accepted in Title Case ("Core Technical Skills").
_HEADING_ENDINGS = (
    ("skills", "skills", True), ("competencies", "skills", True), ("expertise", "skills", True),
    ("tech stack", "skills", True), ("technologies", "skills", False),
    ("experience", "experience", False), ("employment", "experience", False),
    ("projects", "projects", False), ("education", "education", False), ("qualifications", "education", False),
    ("certifications", "certifications", False), ("certificates", "certifications", False),
    ("summary", "summary", False), ("objective", "summary", False),
)


def _heading_style(text: str) -> str | None:
    """"strong" (ALL CAPS or ends with ':'), "title" (Title Case), or None for an ordinary line."""
    words = text.rstrip(":").split()
    if not 1 <= len(words) <= 5:
        return None
    letters = [c for c in text if c.isalpha()]
    if text.endswith(":") or (letters and all(c.isupper() for c in letters)):
        return "strong"
    if all(w[0].isupper() or w.lower() in ("and", "&", "of", "the") for w in words if w[0].isalpha()):
        return "title"
    return None


def _heading(line: Line) -> str | None:
    if line.bullet or len(line.text) > 45:
        return None
    key = re.sub(r"[:\s]+$", "", line.text).strip().lower()
    if key in _HEADING_LOOKUP:
        return _HEADING_LOOKUP[key]
    if key in _OTHER_HEADINGS:
        return "other:" + line.text.strip().rstrip(":").title()
    if style := _heading_style(line.text.strip()):
        tail = " ".join(re.sub(r"[^a-z& ]+", " ", key).split()[-2:])
        for ending, section, title_ok in _HEADING_ENDINGS:
            if tail.endswith(ending) and (style == "strong" or title_ok):
                return section
    return None


# ---------------------------------------------------------------- dates

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_POINT = rf"(?:{_MONTH}\.?\s+\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
_END = rf"(?:{_POINT}|present|current|now|till date|to date|ongoing)"
DATE_RANGE_RE = re.compile(rf"(?P<start>{_POINT})\s*(?:–|—|-|to)\s*(?P<end>{_END})", re.IGNORECASE)


def parse_point(text: str) -> date | None:
    text = text.strip().lower().rstrip(".")
    if m := re.fullmatch(rf"({_MONTH})\.?\s+(\d{{4}})", text):
        return date(int(m.group(2)), _MONTHS[m.group(1)[:3]], 1)
    if m := re.fullmatch(r"(\d{1,2})/(\d{4})", text):
        month = int(m.group(1))
        return date(int(m.group(2)), month, 1) if 1 <= month <= 12 else None
    if m := re.fullmatch(r"(\d{4})", text):
        return date(int(m.group(1)), 1, 1)
    return None


def _strip_separators(text: str) -> str:
    return re.sub(r"^[\s|·,–—-]+|[\s|·,–—-]+$", "", text)


# ---------------------------------------------------------------- parser


def _is_continuation(previous: str, line: Line) -> bool:
    """A wrapped line of the previous bullet, rather than a new entry heading."""
    if line.bullet:
        return False
    # A line carrying a date range ("Associate Engineer  Nov 2022 – Jan 2024") starts a new role, even
    # when the bullet before it wrapped without a full stop. Bullets rarely contain a full date range.
    if DATE_RANGE_RE.search(line.text) and not line.text[0].islower() and len(line.text) <= 120:
        return False
    first = line.text[0]
    return not re.search(r"[.!?;:)\]]$", previous.strip()) or first.islower() or first.isdigit() or first in ",;)&"


def _split_list(value: str) -> list[str]:
    items, depth, current = [], 0, []
    for ch in value:
        depth += ch == "("
        depth -= ch == ")"
        if ch in ",;" and depth <= 0:
            items.append("".join(current))
            current = []
        else:
            current.append(ch)
    items.append("".join(current))
    return [i.strip().rstrip(".") for i in items if i.strip()]


def _is_tech_line(text: str) -> bool:
    parts = [p.strip() for p in re.split(r"\s+[·|]\s+", text) if p.strip()]
    return len(parts) >= 3 and sum(len(p.split()) for p in parts) / len(parts) <= 4


class _Parser:
    def __init__(self, lines: list[Line]) -> None:
        self.lines = lines
        self.doc = ResumeDocument()

    def run(self) -> ResumeDocument:
        sections: list[tuple[str, list[Line]]] = [("header", [])]
        for line in self.lines:
            if heading := _heading(line):
                sections.append((heading, []))
            else:
                sections[-1][1].append(line)
        for name, body in sections:
            handler = getattr(self, f"_{name}", None)
            if name.startswith("other:"):
                self.doc.extra_sections.append(ExtraSection(title=name[6:], lines=[ln.text for ln in body]))
            elif handler is not None:
                handler(body)
        self._check()
        return self.doc

    def _header(self, body: list[Line]) -> None:
        contact = Contact()
        rest: list[str] = []
        for i, line in enumerate(body):
            text = line.text
            email = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)
            phone = re.search(r"\+?\d[\d\s-]{8,}\d", text)
            if i == 0 and not email:
                contact.name = text
                continue
            if email or phone or "linkedin" in text.lower():
                contact.email = contact.email or (email.group(0) if email else None)
                contact.phone = contact.phone or (phone.group(0).strip() if phone else None)
                for part in re.split(r"\s*\|\s*", text):
                    part = part.strip()
                    if re.search(r"linkedin\.com|github\.com|https?://", part, re.I):
                        contact.links.append(part)
                    elif part and not re.search(r"@|\d{6,}", part) and not contact.location:
                        contact.location = part
                continue
            rest.append(text)
        if rest:
            contact.headline = _strip_separators(" ".join(rest))
        self.doc.contact = contact

    def _summary(self, body: list[Line]) -> None:
        self.doc.summary = " ".join(ln.text for ln in body)

    def _skills(self, body: list[Line]) -> None:
        # Collect each group's text first: a long line wraps mid-item ("Apache" / "Kafka"), so a wrapped
        # line joins the previous one before the list is split into items.
        raw: list[list[str]] = []
        for line in body:
            if m := re.match(r"^([A-Za-z&/,+ .-]{2,40}):\s*(.+)$", line.text):
                raw.append([m.group(1).strip(), m.group(2).strip()])
            elif raw:
                raw[-1][1] = f"{raw[-1][1].rstrip()} {line.text.strip()}"
            else:
                raw.append(["Skills", line.text.strip()])
        self.doc.skills = [SkillGroup(name=name, items=_split_list(text)) for name, text in raw]

    def _blocks(self, body: list[Line]) -> list[tuple[list[str], list[str]]]:
        """Group lines into (heading lines, bullet texts) blocks, joining wrapped bullet lines."""
        blocks: list[tuple[list[str], list[str]]] = []
        heading: list[str] = []
        bullets: list[str] = []
        for line in body:
            if line.bullet:
                bullets.append(line.text)
            elif bullets and _is_continuation(bullets[-1], line):
                bullets[-1] = f"{bullets[-1]} {line.text}"
            else:
                # A new block starts after bullets, or at a second dated heading (entries without bullets).
                if bullets or (DATE_RANGE_RE.search(line.text) and any(DATE_RANGE_RE.search(h) for h in heading)):
                    blocks.append((heading, bullets))
                    heading, bullets = [], []
                heading.append(line.text)
        if heading or bullets:
            blocks.append((heading, bullets))
        return blocks

    def _experience(self, body: list[Line]) -> None:
        for n, (heading, bullets) in enumerate(self._blocks(body), start=1):
            title = company = location = None
            start = end = None
            is_current = False
            date_text = ""
            for i, text in enumerate(heading):
                if m := DATE_RANGE_RE.search(text):
                    date_text = m.group(0)
                    start = parse_point(m.group("start"))
                    end = parse_point(m.group("end"))
                    is_current = end is None
                    remainder = _strip_separators(text[: m.start()] + text[m.end():])
                    if remainder:
                        if title is None and i == 0:
                            title = remainder.split("  |  ")[0].strip()
                        else:
                            location = location or remainder
                    continue
                parts = [p.strip() for p in re.split(r"\s+\|\s+", text) if p.strip()]
                if not parts:
                    continue
                if title is None:
                    title = parts[0]
                elif company is None:
                    company = parts[0]
                    if len(parts) > 1:
                        location = location or " | ".join(parts[1:])
                else:
                    location = location or text
            if title is None and company is None:
                if bullets:
                    self.doc.warnings.append("experience bullets found without a job heading; check the experience section")
                continue
            entry = ExperienceEntry(
                id=f"e{n}",
                title=title or "",
                company=company or "",
                location=location,
                start=start,
                end=end,
                is_current=is_current,
                date_text=date_text,
                is_internship=bool(re.search(r"\bintern(ship)?\b", title or "", re.I)),
                bullets=[Bullet(id=f"e{n}b{i}", text=t) for i, t in enumerate(bullets, start=1)],
            )
            self.doc.experience.append(entry)

    def _projects(self, body: list[Line]) -> None:
        for n, (heading, bullets) in enumerate(self._blocks(body), start=1):
            if not heading:
                continue
            name, *rest = heading
            subtitle_parts, technologies = [], []
            for text in rest:
                if _is_tech_line(text) and not technologies:
                    technologies = [p.strip() for p in re.split(r"\s+[·|]\s+", text) if p.strip()]
                else:
                    subtitle_parts.append(text)
            self.doc.projects.append(
                ProjectEntry(
                    id=f"p{n}",
                    name=name,
                    subtitle=" ".join(subtitle_parts) or None,
                    technologies=technologies,
                    bullets=[Bullet(id=f"p{n}b{i}", text=t) for i, t in enumerate(bullets, start=1)],
                )
            )

    def _education(self, body: list[Line]) -> None:
        self.doc.education = [ln.text for ln in body]

    def _certifications(self, body: list[Line]) -> None:
        self.doc.certifications = [ln.text for ln in body]

    def _check(self) -> None:
        doc = self.doc
        if not doc.contact.name:
            doc.warnings.append("could not find your name at the top of the resume")
        if not doc.contact.email:
            doc.warnings.append("no email address found in the header")
        if not doc.experience:
            doc.warnings.append("no experience section found")
        for entry in doc.experience:
            if entry.start is None:
                doc.warnings.append(f"no dates found for '{entry.title}'; experience totals will be incomplete")
            if not entry.company:
                doc.warnings.append(f"no company found for '{entry.title}'")
        if not doc.skills:
            doc.warnings.append("no skills section found")


def parse_resume(data: bytes, filename: str) -> tuple[str, ResumeDocument]:
    fmt, lines = extract_lines(data, filename)
    if not lines:
        raise ResumeParseError("no text found; scanned (image-only) PDFs are not supported")
    return fmt, _Parser(lines).run()

"""Layout checks on the generated files themselves (not on the data that produced them).

PDF: opens, no blank pages, every font embedded, text inside the printable area, font sizes within
the style limits, sections in reading order, every bullet and role present in the extracted text,
no heading or role/project title stranded at the bottom of a page, and a reasonable page count.
DOCX: opens, paragraph properties in schema order, pagination flags on headings and bullets,
consistent bullet formatting, the configured font, and the same content as the PDF.

These checks catch regressions; they cannot prove a layout is beautiful or that every ATS reads it
the same way, so warnings ask for a visual review of the page previews.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ..domain import ResumeDocument
from .render import _company_line, _sections
from .style import DOCX_FONT, ResumeStyle

_PPR_ORDER = ("pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr",
              "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
              "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd", "snapToGrid",
              "spacing", "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection",
              "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange")


@dataclass
class TextRun:
    page: int
    x: float
    y: float
    size: float
    text: str


def squash(text: str) -> str:
    """Normalise for content comparison: no-break spaces, line breaks and runs of spaces."""
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip().lower()


def _runs(reader) -> list[TextRun]:  # noqa: ANN001
    runs: list[TextRun] = []
    for number, page in enumerate(reader.pages, start=1):
        def visit(text, cm, tm, _font, size, number=number):  # noqa: ANN001
            if text.strip():
                scale = abs(tm[3] * cm[3]) or 1
                runs.append(TextRun(number, tm[4] * cm[0] + cm[4], tm[5] * cm[3] + cm[5], round(size * scale, 1), text))
        page.extract_text(visitor_text=visit)
    return runs


def _embedded(reader) -> list[str]:  # noqa: ANN001
    missing = set()
    for page in reader.pages:
        fonts = (page.get("/Resources") or {}).get("/Font") or {}
        for ref in fonts.values():
            font = ref.get_object()
            descriptor = font.get("/FontDescriptor")
            if descriptor is None and "/DescendantFonts" in font:
                descriptor = font["/DescendantFonts"][0].get_object().get("/FontDescriptor")
            descriptor = descriptor.get_object() if descriptor is not None else {}
            if not any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3")):
                missing.add(str(font.get("/BaseFont")))
    return sorted(missing)


def inspect_pdf(path: Path, doc: ResumeDocument, style: ResumeStyle) -> list[tuple[str, bool, str, str]]:
    """Returns (check, passed, detail, severity) tuples."""
    import pypdf

    out: list[tuple[str, bool, str, str]] = []
    try:
        reader = pypdf.PdfReader(io.BytesIO(path.read_bytes()))
        pages = len(reader.pages)
    except Exception as exc:  # any parse failure means the file is unusable
        return [("PDF opens", False, f"cannot open the PDF: {exc}", "error")]
    out.append(("PDF opens", True, f"{pages} page(s)", "error"))
    texts = [page.extract_text() or "" for page in reader.pages]
    blank = [i + 1 for i, t in enumerate(texts) if len(t.split()) < 5]
    out.append(("no blank pages", not blank, f"blank page(s): {blank}", "error"))
    missing_fonts = _embedded(reader)
    out.append(("fonts embedded", not missing_fonts, f"not embedded: {', '.join(missing_fonts)}", "error"))

    width, height = (float(x) for x in reader.pages[0].mediabox[2:])
    margin = style.margin_in * 72
    runs = _runs(reader)
    outside = [r for r in runs if not (margin - 3 <= r.x <= width - margin and margin * 0.3 <= r.y <= height - margin + 3)]
    out.append(("text inside the printable area", not outside,
                f"{len(outside)} text run(s) outside the margins, e.g. '{outside[0].text.strip()[:40]}'" if outside else "",
                "error"))
    sizes = Counter(r.size for r in runs for _ in r.text.split())
    body = sizes.most_common(1)[0][0] if sizes else 0
    out.append(("body font size", style.min_body_pt - 0.05 <= body <= style.max_body_pt + 0.05,
                f"body text is {body}pt; allowed {style.min_body_pt}–{style.max_body_pt}pt", "error"))
    extremes = [s for s in sizes if not (style.footer_pt - 0.5 <= s <= style.name_pt + 0.5)]
    out.append(("font sizes within limits", not extremes, f"unexpected sizes: {sorted(extremes)}", "error"))

    full = squash(" ".join(texts))
    heads = [h for h in _sections(doc)]
    positions = [full.find(h.lower()) for h in heads]
    out.append(("sections in reading order", -1 not in positions and positions == sorted(positions),
                "sections missing or out of order: " + ", ".join(h for h, p in zip(heads, positions) if p == -1), "error"))
    first_line = squash(texts[0].strip().split("\n")[0]) if texts and texts[0].strip() else ""
    out.append(("name read first", first_line == squash(doc.contact.name),
                f"the text layer starts with '{first_line[:40]}', not the name", "error"))
    lost = [b.text[:60] for b in doc.all_bullets() if squash(b.text) not in full]
    lost += [e.title for e in doc.experience if squash(e.title) not in full]
    lost += [e.date_text for e in doc.experience if e.date_text and squash(e.date_text) not in full]
    out.append(("all content present in PDF text", not lost, "missing from extracted text: " + "; ".join(lost[:3]), "error"))

    # Stranded headings: the last line of a page (above the footer) must not open a new block.
    openers = {squash(h) for h in heads}
    openers |= {squash(e.title) for e in doc.experience} | {squash(_company_line(e)) for e in doc.experience}
    openers |= {squash(p.name) for p in doc.projects} | {squash(p.subtitle or "") for p in doc.projects} - {""}
    footer_y = margin * 0.3 + style.footer_pt + 8
    stranded = []
    for page in range(1, pages):
        lines = sorted((r for r in runs if r.page == page and r.y > footer_y), key=lambda r: r.y)
        if not lines:
            continue
        bottom_y = lines[0].y
        last_line = squash(" ".join(r.text for r in lines if abs(r.y - bottom_y) < 1.5))
        if any(last_line and (last_line == o or (o and last_line.startswith(o) and len(o) > 8)) for o in openers):
            stranded.append(f"page {page}: '{last_line[:50]}'")
    out.append(("no stranded headings at page ends", not stranded, "; ".join(stranded), "error"))
    out.append(("page count", pages <= style.target_pages + 1,
                f"{pages} pages; aim for {style.target_pages} unless the content needs more", "warning"))
    return out


def inspect_docx(path: Path, doc: ResumeDocument, style: ResumeStyle, pdf_text: str) -> list[tuple[str, bool, str, str]]:
    import docx

    out: list[tuple[str, bool, str, str]] = []
    try:
        document = docx.Document(str(path))
    except Exception as exc:
        return [("DOCX opens", False, f"cannot open the DOCX: {exc}", "error")]
    out.append(("DOCX opens", True, "", "error"))
    bad_order = 0
    for p in document.paragraphs:
        ppr = p._p.pPr
        if ppr is None:
            continue
        names = [c.tag.split("}")[1] for c in ppr]
        ranks = [_PPR_ORDER.index(n) for n in names if n in _PPR_ORDER]
        bad_order += ranks != sorted(ranks)
    out.append(("DOCX XML in schema order", bad_order == 0, f"{bad_order} paragraph(s) with out-of-order properties", "error"))
    out.append(("DOCX font", document.styles["Normal"].font.name == DOCX_FONT,
                f"Normal style font is {document.styles['Normal'].font.name}", "warning"))
    heads = set(_sections(doc))
    headings = [p for p in document.paragraphs if p.text in heads]
    out.append(("DOCX headings keep with next", bool(headings) and all(p.paragraph_format.keep_with_next for p in headings),
                "a section heading can be separated from its content", "error"))
    bullets = [p for p in document.paragraphs if p.style is not None and p.style.name == "List Bullet"]
    indents = {(p.paragraph_format.left_indent, p.paragraph_format.first_line_indent) for p in bullets}
    out.append(("DOCX bullets consistent", len(indents) <= 1 and all(p.paragraph_format.keep_together for p in bullets),
                f"{len(indents)} different bullet indents, or bullets allowed to split", "error"))
    docx_text = squash(" ".join(p.text for p in document.paragraphs))
    lost = [b.text[:60] for b in doc.all_bullets() if squash(b.text) not in docx_text]
    out.append(("all content present in DOCX", not lost, "missing: " + "; ".join(lost[:3]), "error"))
    pdf = squash(pdf_text)
    differ = [b.text[:60] for b in doc.all_bullets() if (squash(b.text) in docx_text) != (squash(b.text) in pdf)]
    out.append(("DOCX and PDF have the same content", not differ, "differs: " + "; ".join(differ[:3]), "error"))
    return out


def render_previews(pdf_path: Path, folder: Path, dpi: int = 70) -> list[Path]:
    """Page images for visual review. Needs poppler's pdftoppm; skipped (empty list) without it."""
    if shutil.which("pdftoppm") is None:
        return []
    folder.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(pdf_path), str(folder / "page")],
                       check=True, timeout=60, capture_output=True)
    except (subprocess.SubprocessError, OSError):
        return []
    return sorted(folder.glob("page-*.png"))

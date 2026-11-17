"""Render a ``ResumeDocument`` to DOCX and PDF from one style specification (``style.py``).

Both formats use the same page, font metrics, sizes and spacing, and the same pagination rules:

* a section heading, a role's title/company line, and a project's name/stack lines are kept with
  the first bullet that follows (never stranded at the bottom of a page)
* bullets of up to ``max_unsplit_bullet_lines`` lines never split across pages; longer ones split
  without widow or orphan lines
* nothing is repeated across pages: no header or footer (many ATS parsers read them into the name
  or the first job) and no "(continued)" title, which a parser can count as another job
* plain spaces only: a no-break space can make an ATS miss a keyword such as "Spring Boot"

``render_resume`` picks the first style variant (standard, then compact, both inside the font and
spacing limits) whose PDF fits the target page count, then renders the DOCX with the same variant.
Layout is ATS-friendly: single column, standard headings, plain bullets, no tables, images, text
boxes, headers or footers. In the PDF a role's title and dates share one text line (title first).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from ..domain import ResumeDocument
from .style import DOCX_FONT, STANDARD, ResumeStyle, fit_levels

_FONT_CANDIDATES = (
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
)
HEADING_COLOR = (0x1F, 0x2A, 0x44)


@dataclass
class RenderResult:
    style: ResumeStyle
    pages: int
    last_page_fill: float  # 0–1, how much of the last page is used
    continued: list[str] = field(default_factory=list)  # entries that run onto a following page



def _sections(doc: ResumeDocument) -> list[str]:
    return [s for s, present in (
        ("PROFESSIONAL SUMMARY", doc.summary),
        ("TECHNICAL SKILLS", doc.skills),
        ("PROFESSIONAL EXPERIENCE", doc.experience),
        ("PROJECTS", doc.projects),
        ("EDUCATION", doc.education),
        ("CERTIFICATIONS", doc.certifications),
    ) if present]


def _contact_line(doc: ResumeDocument) -> str:
    c = doc.contact
    return "  |  ".join(x for x in [c.email, c.phone, c.location, *c.links] if x)


def _company_line(entry) -> str:  # noqa: ANN001
    return " | ".join(x for x in (entry.company, entry.location) if x)


def _entry_label(entry) -> str:  # noqa: ANN001
    return f"{entry.title} — {entry.company}" if entry.company else entry.title


def render_resume(doc: ResumeDocument, docx_path: Path, pdf_path: Path, style: ResumeStyle = STANDARD) -> RenderResult:
    """Render both formats with the same style variant, chosen by how the PDF paginates."""
    results: list[RenderResult] = []
    for variant in fit_levels(style):
        result = render_pdf(doc, pdf_path, variant)
        results.append(result)
        if result.pages <= variant.target_pages:
            break
    # A tighter variant is used only when it saves a page; otherwise the content genuinely needs
    # the extra page and the standard look is kept.
    best = min(results, key=lambda r: (r.pages, results.index(r)))
    if best is not results[-1]:
        best = render_pdf(doc, pdf_path, best.style)  # the file on disk must be the chosen variant
    render_docx(doc, docx_path, best.style)
    return best


# ---------------------------------------------------------------- DOCX


# w:pPr children that must follow w:pBdr (ECMA-376 CT_PPrBase sequence).
_PPR_AFTER_PBDR = ("w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct",
                   "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd", "w:snapToGrid",
                   "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
                   "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId",
                   "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")


def _docx_border_bottom(paragraph) -> None:  # noqa: ANN001
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    ppr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for key, value in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", "8A93A6")):
        bottom.set(qn(key), value)
    borders.append(bottom)
    # Schema order matters (Word reports out-of-order elements as unreadable content): pBdr comes
    # after keepNext/widowControl/numPr and before shd, tabs, spacing, ind and jc.
    ppr.insert_element_before(borders, *_PPR_AFTER_PBDR)


def _docx_field(paragraph, instruction: str) -> None:  # noqa: ANN001
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), instruction)
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    fld.append(run)
    paragraph._p.append(fld)


def render_docx(doc: ResumeDocument, path: Path, style: ResumeStyle = STANDARD) -> None:
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    document = docx.Document()
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.27), Inches(11.69)  # A4
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Inches(style.margin_in))
    section.footer_distance = Inches(style.margin_in / 2)
    content_width = section.page_width - section.left_margin - section.right_margin

    normal = document.styles["Normal"]
    normal.font.name = DOCX_FONT
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), DOCX_FONT)
    normal.font.size = Pt(style.body_pt)
    nf = normal.paragraph_format
    nf.space_before, nf.space_after = Pt(0), Pt(style.paragraph_space_after_pt)
    nf.line_spacing = Pt(style.leading(style.body_pt))  # exact, the same leading as the PDF
    nf.widow_control = True

    def para(text: str = "", *, bold: bool = False, size: float | None = None, center: bool = False,
             space_before: float | None = None, space_after: float | None = None, keep_next: bool = False,
             style_name: str | None = None, italic: bool = False):
        p = document.add_paragraph(style=style_name)
        if text:
            run = p.add_run(plain(text))
            run.bold, run.italic = bold, italic
            if size:
                run.font.size = Pt(size)
        pf = p.paragraph_format
        if size:
            pf.line_spacing = Pt(style.leading(size))
        if center:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if space_before is not None:
            pf.space_before = Pt(space_before)
        if space_after is not None:
            pf.space_after = Pt(space_after)
        pf.keep_with_next = keep_next
        return p

    def heading(text: str) -> None:
        p = para(text, bold=True, size=style.heading_pt, space_before=style.heading_space_before_pt,
                 space_after=style.heading_space_after_pt, keep_next=True)
        p.runs[0].font.color.rgb = RGBColor(*HEADING_COLOR)
        if style.heading_rule:
            _docx_border_bottom(p)

    def bullets(texts: list[str]) -> None:
        for text in texts:
            p = para(text, style_name="List Bullet", space_after=style.bullet_space_after_pt)
            pf = p.paragraph_format
            pf.left_indent, pf.first_line_indent = Inches(style.bullet_indent_in), Inches(-style.bullet_indent_in)
            pf.keep_together = True  # a bullet never splits across pages
            pf.keep_with_next = False

    para(doc.contact.name, bold=True, size=style.name_pt, center=True, space_after=1)
    if doc.contact.headline:
        para(doc.contact.headline, size=style.headline_pt, center=True, space_after=1)
    para(_contact_line(doc), size=style.contact_pt, center=True, space_after=2)

    for name in _sections(doc):
        heading(name)
        if name == "PROFESSIONAL SUMMARY":
            para(doc.summary)
        elif name == "TECHNICAL SKILLS":
            for group in doc.skills:
                p = document.add_paragraph()
                p.add_run(f"{plain(group.name)}: ").bold = True
                p.add_run(plain(", ".join(group.items)))
        elif name == "PROFESSIONAL EXPERIENCE":
            for entry in doc.experience:
                p = para(space_before=style.entry_space_before_pt, space_after=0, keep_next=True)
                p.paragraph_format.tab_stops.add_tab_stop(content_width, WD_TAB_ALIGNMENT.RIGHT)
                p.add_run(plain(entry.title)).bold = True
                p.add_run(f"\t{plain(entry.date_text)}")
                para(_company_line(entry), italic=True, keep_next=bool(entry.bullets), space_after=2)
                bullets([b.text for b in entry.bullets])
        elif name == "PROJECTS":
            for project in doc.projects:
                para(project.name, bold=True, space_before=style.entry_space_before_pt, space_after=0, keep_next=True)
                if project.subtitle:
                    para(project.subtitle, italic=True, space_after=0, keep_next=True)
                if project.technologies:
                    para(" · ".join(project.technologies), size=style.small_pt, keep_next=bool(project.bullets), space_after=2)
                bullets([b.text for b in project.bullets])
        elif name == "EDUCATION":
            for i, line in enumerate(doc.education):
                para(line, keep_next=i < len(doc.education) - 1)
        elif name == "CERTIFICATIONS":
            bullets(doc.certifications)
    for extra in doc.extra_sections:
        heading(extra.title.upper())
        for i, line in enumerate(extra.lines):
            para(line, keep_next=i < len(extra.lines) - 1)

    if style.page_numbers:
        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = footer.add_run(f"{doc.contact.name}  ·  Page ")
        run.font.size = Pt(style.footer_pt)
        _docx_field(footer, "PAGE")
        footer.add_run(" of ").font.size = Pt(style.footer_pt)
        _docx_field(footer, "NUMPAGES")
        for r in footer.runs:
            r.font.size, r.font.color.rgb = Pt(style.footer_pt), RGBColor(0x6B, 0x72, 0x80)
    core = document.core_properties
    core.author = doc.contact.name
    core.title = f"Resume - {doc.contact.name}"
    core.comments = ""
    document.save(str(path))


# ---------------------------------------------------------------- PDF


@lru_cache
def _pdf_fonts() -> tuple[str, str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for regular, bold, italic in _FONT_CANDIDATES:
        if Path(regular).exists() and Path(bold).exists() and Path(italic).exists():
            pdfmetrics.registerFont(TTFont("ResumeSans", regular))
            pdfmetrics.registerFont(TTFont("ResumeSans-Bold", bold))
            pdfmetrics.registerFont(TTFont("ResumeSans-Italic", italic))
            return "ResumeSans", "ResumeSans-Bold", "ResumeSans-Italic"
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"


_ODD_SPACES = re.compile("[\u00a0\u2000-\u200a\u202f\u205f\u3000]")
_ZERO_WIDTH = re.compile("[\u200b-\u200d\u2060\ufeff]")


def plain(text: str) -> str:
    """Ordinary spaces only (a parsed master can carry no-break or zero-width spaces)."""
    return _ODD_SPACES.sub(" ", _ZERO_WIDTH.sub("", text))


def _pdf_safe(text: str, font: str) -> str:
    text = plain(text)
    if font.startswith("Helvetica"):  # built-in fonts lack some glyphs
        text = text.replace("→", "->").replace("✓", "-")
    return escape(text)


def render_pdf(doc: ResumeDocument, path: Path, style: ResumeStyle = STANDARD) -> RenderResult:
    """Two passes: the first counts pages for the "Page X of Y" footer."""
    first = _render_pdf_pass(doc, path, style, total_pages=None)
    if not style.page_numbers:
        return first
    return _render_pdf_pass(doc, path, style, total_pages=first.pages)


def _render_pdf_pass(doc: ResumeDocument, path: Path, style: ResumeStyle, *, total_pages: int | None) -> RenderResult:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.platypus import Flowable, Frame, HRFlowable, PageTemplate, Paragraph, Spacer
    from reportlab.platypus.doctemplate import BaseDocTemplate

    regular, bold, italic = _pdf_fonts()
    lead = style.leading
    base = ParagraphStyle("base", fontName=regular, fontSize=style.body_pt, leading=lead(style.body_pt),
                          spaceAfter=style.paragraph_space_after_pt, allowWidows=0, allowOrphans=0)
    s = {
        "name": ParagraphStyle("name", parent=base, fontName=bold, fontSize=style.name_pt, leading=lead(style.name_pt),
                               alignment=TA_CENTER, spaceAfter=1),
        "headline": ParagraphStyle("headline", parent=base, fontSize=style.headline_pt, leading=lead(style.headline_pt),
                                   alignment=TA_CENTER, spaceAfter=1),
        "contact": ParagraphStyle("contact", parent=base, fontSize=style.contact_pt, leading=lead(style.contact_pt),
                                  alignment=TA_CENTER, spaceAfter=2),
        "heading": ParagraphStyle("heading", parent=base, fontName=bold, fontSize=style.heading_pt,
                                  leading=lead(style.heading_pt), spaceBefore=style.heading_space_before_pt, spaceAfter=1,
                                  textColor=HexColor("#%02X%02X%02X" % HEADING_COLOR), keepWithNext=1),
        "role": ParagraphStyle("role", parent=base, fontName=bold, spaceAfter=0),
        "role_long": ParagraphStyle("role_long", parent=base, fontName=bold, spaceBefore=style.entry_space_before_pt,
                                    spaceAfter=0, keepWithNext=1),
        "dates": ParagraphStyle("dates", parent=base, spaceAfter=0, keepWithNext=1),
        "company": ParagraphStyle("company", parent=base, fontName=italic, spaceAfter=2, keepWithNext=1),
        "project": ParagraphStyle("project", parent=base, fontName=bold, spaceBefore=style.entry_space_before_pt,
                                  spaceAfter=0, keepWithNext=1),
        "subtitle": ParagraphStyle("subtitle", parent=base, fontName=italic, spaceAfter=0, keepWithNext=1),
        "tech": ParagraphStyle("tech", parent=base, fontSize=style.small_pt, leading=lead(style.small_pt), spaceAfter=2,
                               keepWithNext=1),
        "bullet": ParagraphStyle("bullet", parent=base, leftIndent=style.bullet_indent_in * inch, bulletIndent=1,
                                 bulletFontName=regular, spaceAfter=style.bullet_space_after_pt),
        "continued": ParagraphStyle("continued", parent=base, fontName=italic, textColor=HexColor("#4B5563"),
                                    spaceAfter=2),
        "keep": ParagraphStyle("keep", parent=base, keepWithNext=1),
    }

    def p(text: str, key: str = "") -> Paragraph:
        return Paragraph(_pdf_safe(text, regular), s[key] if key else base)

    class Bullet(Paragraph):
        """A bullet that moves to the next page whole unless it is longer than the limit."""

        entry: str | None = None

        def split(self, aW, aH):  # noqa: ANN001, ANN201
            self.wrap(aW, 10**6)
            if len(self.blPara.lines) <= style.max_unsplit_bullet_lines:
                return []
            parts = super().split(aW, aH)
            for part in parts:
                part.entry = self.entry
            return parts

    class EntryStart(Spacer):
        def __init__(self, label: str) -> None:
            super().__init__(0, 0)
            self.label = label

    class EntryEnd(Spacer):
        def __init__(self) -> None:
            super().__init__(0, 0)

    width = A4[0] - 2 * style.margin_in * inch
    margin = style.margin_in * inch
    footer_space = (style.footer_pt + 6) if style.page_numbers else 0

    class ResumeDoc(BaseDocTemplate):
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            super().__init__(*args, **kwargs)
            self.current_entry: str | None = None
            self.pending_continuation = False
            self.continued: list[str] = []
            self.last_y = 0.0

        def afterFlowable(self, flowable) -> None:  # noqa: ANN001, N802
            if isinstance(flowable, EntryStart):
                self.current_entry = flowable.label
            elif isinstance(flowable, EntryEnd):
                self.current_entry = None
            if self.frame is not None:  # None between pages
                self.last_y = self.frame._y

        def handle_pageBegin(self) -> None:  # noqa: N802
            super().handle_pageBegin()
            self.pending_continuation = style.continuation_marker and self.current_entry is not None

        def handle_flowable(self, flowables) -> None:  # noqa: ANN001
            if self.pending_continuation and flowables:
                self.pending_continuation = False
                if isinstance(flowables[0], Bullet) and self.current_entry:
                    self.continued.append(self.current_entry)
                    flowables.insert(0, p(f"{self.current_entry} (continued)", "continued"))
            super().handle_flowable(flowables)

    def footer(canvas, document) -> None:  # noqa: ANN001
        if not style.page_numbers:
            return
        canvas.saveState()
        canvas.setFont(regular, style.footer_pt)
        canvas.setFillColor(HexColor("#6B7280"))
        total = f" of {total_pages}" if total_pages else ""
        canvas.drawCentredString(A4[0] / 2, margin / 2, f"{doc.contact.name}  ·  Page {document.page}{total}")
        canvas.restoreState()

    frame = Frame(margin, margin + footer_space, width, A4[1] - 2 * margin - footer_space,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="body")
    document = ResumeDoc(str(path), pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=margin,
                         bottomMargin=margin, title=f"Resume - {doc.contact.name}", author=doc.contact.name,
                         subject="", creator="hirefinch", keywords="", initialFontName=regular,
                         initialFontSize=style.body_pt)
    # Drawn at the end of each page so the footer comes after the content in the text layer.
    document.addPageTemplates([PageTemplate(id="page", frames=[frame], onPageEnd=footer)])

    def heading(text: str) -> list:
        rule = HRFlowable(width="100%", thickness=0.6, color=HexColor("#8A93A6"), spaceBefore=0,
                          spaceAfter=style.heading_space_after_pt)
        rule.keepWithNext = 1
        return [p(text, "heading"), rule] if style.heading_rule else [p(text, "heading")]

    class RoleLine(Flowable):
        """Title on the left and dates on the right as plain text on one line (no table), so an ATS
        reads "Title  Dates" in order."""

        def __init__(self, title: str, dates: str) -> None:
            super().__init__()
            self.title, self.dates = title, dates
            self.spaceBefore = style.entry_space_before_pt
            self.keepWithNext = 1

        def wrap(self, aW, aH):  # noqa: ANN001, ANN201
            self.width, self.height = aW, lead(style.body_pt)
            return self.width, self.height

        def draw(self) -> None:
            # One text object on one baseline: extractors (and ATS parsers) read "Title  Dates" as a line.
            title, dates = plain(self.title), plain(self.dates)
            text = self.canv.beginText(0, self.height - style.body_pt)  # the baseline a one-line Paragraph uses
            text.setFont(bold, style.body_pt)
            text.textOut(title)
            text.setFont(regular, style.body_pt)
            text.moveCursor(self.width - stringWidth(dates, regular, style.body_pt), 0)
            text.textOut(dates)
            self.canv.drawText(text)

    def role_line(title: str, dates: str) -> list:
        if stringWidth(title, bold, style.body_pt) + stringWidth(dates, regular, style.body_pt) + 12 <= width:
            return [RoleLine(title, dates)]
        # A very long title: on its own line(s), dates on the next, still in reading order.
        return [Paragraph(_pdf_safe(title, regular), s["role_long"]), p(dates, "dates")]

    def bullet_list(texts: list[str], entry: str | None) -> list:
        out = []
        for text in texts:
            b = Bullet(_pdf_safe(text, regular), s["bullet"], bulletText="•")
            b.entry = entry
            out.append(b)
        return out

    story: list = [p(doc.contact.name, "name")]
    if doc.contact.headline:
        story.append(p(doc.contact.headline, "headline"))
    story.append(p(_contact_line(doc), "contact"))
    for name in _sections(doc):
        story += heading(name)
        if name == "PROFESSIONAL SUMMARY":
            story.append(Paragraph(_pdf_safe(doc.summary, regular), base))
        elif name == "TECHNICAL SKILLS":
            for group in doc.skills:
                story.append(Paragraph(f"<font name='{bold}'>{_pdf_safe(group.name, regular)}:</font> "
                                       f"{_pdf_safe(', '.join(group.items), regular)}", base))
        elif name == "PROFESSIONAL EXPERIENCE":
            for entry in doc.experience:
                label = _entry_label(entry)
                start = EntryStart(label)
                start.keepWithNext = 1
                story += [start, *role_line(entry.title, entry.date_text), p(_company_line(entry), "company")]
                story += bullet_list([b.text for b in entry.bullets], label)
                story.append(EntryEnd())
        elif name == "PROJECTS":
            for project in doc.projects:
                start = EntryStart(project.name)
                start.keepWithNext = 1
                story += [start, p(project.name, "project")]
                if project.subtitle:
                    story.append(p(project.subtitle, "subtitle"))
                if project.technologies:
                    story.append(p(" · ".join(project.technologies), "tech"))
                story += bullet_list([b.text for b in project.bullets], project.name)
                story.append(EntryEnd())
        elif name == "EDUCATION":
            story += [p(line, "keep" if i < len(doc.education) - 1 else "") for i, line in enumerate(doc.education)]
        elif name == "CERTIFICATIONS":
            story += bullet_list(doc.certifications, None)
    for extra in doc.extra_sections:
        story += heading(extra.title.upper())
        story += [p(line, "keep" if i < len(extra.lines) - 1 else "") for i, line in enumerate(extra.lines)]

    document.build(story)
    frame_height = A4[1] - 2 * margin - footer_space
    used = (margin + footer_space + frame_height - document.last_y) / frame_height
    return RenderResult(style=style, pages=document.page, last_page_fill=round(max(0.0, min(1.0, used)), 2),
                        continued=document.continued)

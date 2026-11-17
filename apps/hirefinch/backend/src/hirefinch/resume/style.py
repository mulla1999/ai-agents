"""One formatting specification for both renderers, so DOCX and PDF use the same page, fonts,
sizes and spacing. ``fit_levels`` lists progressively tighter variants, all within the configured
limits; the renderer picks the first that gives a sensible page count. Fonts never shrink below
``min_body_pt`` to force content onto a page.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# Liberation Sans is metric-compatible with Arial: Word shows the DOCX in Arial and the PDF embeds
# Liberation Sans, so both break lines in the same places.
DOCX_FONT = "Arial"


@dataclass(frozen=True)
class ResumeStyle:
    name: str = "standard"
    page: str = "A4"
    margin_in: float = 0.7
    name_pt: float = 19
    headline_pt: float = 10.5
    contact_pt: float = 9.5
    heading_pt: float = 11.5
    body_pt: float = 10
    small_pt: float = 9  # project technology lines
    footer_pt: float = 8
    line_spacing: float = 1.22  # leading as a multiple of the font size
    heading_space_before_pt: float = 12
    heading_space_after_pt: float = 4
    entry_space_before_pt: float = 7  # before each role or project
    bullet_space_after_pt: float = 3
    paragraph_space_after_pt: float = 2
    bullet_indent_in: float = 0.18  # wrapped lines align with the text, not the bullet
    heading_rule: bool = True
    # Off for ATS: parsers often read footer text ("Name · Page 2 of 2") into the body or the name field,
    # and a repeated "(continued)" role title can be counted as another job.
    page_numbers: bool = False
    continuation_marker: bool = False
    # Bullets up to this many lines never split across pages; longer ones split without widows/orphans.
    max_unsplit_bullet_lines: int = 6
    min_body_pt: float = 9.5
    max_body_pt: float = 10.5
    target_pages: int = 2

    def __post_init__(self) -> None:
        if not self.min_body_pt <= self.body_pt <= self.max_body_pt:
            raise ValueError(f"body font {self.body_pt}pt is outside {self.min_body_pt}–{self.max_body_pt}pt")
        if not 0.5 <= self.margin_in <= 1.0:
            raise ValueError("margins must be between 0.5 and 1.0 inch")
        if not 18 <= self.name_pt <= 22 or not 11 <= self.heading_pt <= 12:
            raise ValueError("name must be 18–22pt and headings 11–12pt")

    def leading(self, size: float) -> float:
        return round(size * self.line_spacing, 2)


STANDARD = ResumeStyle()
# Tighter, still inside every limit: used only when the standard style would spill a few lines
# onto an extra page.
COMPACT = replace(STANDARD, name="compact", margin_in=0.65, body_pt=9.6, contact_pt=9.2, small_pt=8.8,
                  line_spacing=1.18, heading_space_before_pt=10, entry_space_before_pt=5)


def fit_levels(base: ResumeStyle = STANDARD) -> list[ResumeStyle]:
    return [base] if base.name != "standard" else [STANDARD, COMPACT]

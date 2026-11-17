"""Evidence-based resume tailoring.

The tailored resume is derived from the master by *selection and ordering*: the most relevant
skills, bullets and projects move up, the headline lists your strongest matching verified skills,
and older roles may drop their least relevant bullets (reported in the change log). Employers,
titles, dates, education and contact details are copied unchanged.

Nothing is invented. A skill the job wants that your resume does not evidence is reported as a gap.
An optional LLM step may reword the summary and the most relevant bullets. Each reworded bullet keeps
a link to its master bullet, and the validator rejects any wording that adds or drops a number or
technology, claims more responsibility, or stops describing the same achievement.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from ..candidate import CandidateProfile
from ..domain import Bullet, ParsedJob, Profile, ResumeDocument, SkillGroup
from ..skills import ROLE_FAMILIES, category_of, extract_skills
from ..text import keywords

TEMPLATE_VERSION = "ats-classic-2"
TAILOR_VERSION = "tailor-2"


@dataclass
class TailorResult:
    document: ResumeDocument
    role_family: str
    changes: list[str] = field(default_factory=list)
    omitted_bullets: list[dict[str, str]] = field(default_factory=list)
    keyword_coverage: dict[str, list[str]] = field(default_factory=dict)
    diff: str = ""
    rewrites: list[dict[str, str]] = field(default_factory=list)  # LLM rewordings that passed every check
    rejected_rewrites: list[dict[str, str]] = field(default_factory=list)


class _Relevance:
    def __init__(self, parsed: ParsedJob, family: str) -> None:
        self.required = set(parsed.required_skills)
        self.preferred = set(parsed.preferred_skills)
        self.jd_keywords = set(parsed.keywords)
        self.family_categories = set(ROLE_FAMILIES.get(family, {}).get("categories", ()))  # type: ignore[arg-type]

    def score(self, text: str) -> float:
        skills = extract_skills(text)
        value = 0.0
        for s in skills:
            weight = 2.0 if s in self.required else 1.0 if s in self.preferred else 0.0
            # Skills central to the role family count double, so an AI role leads with AI work
            # rather than with whichever bullet lists the most technologies.
            value += weight * (2.0 if category_of(s) in self.family_categories else 1.0)
        value += min(1.5, 0.25 * len(keywords(text) & self.jd_keywords))
        return value


def render_text(doc: ResumeDocument) -> str:
    """Plain-text rendering, used for comparisons and ATS checks."""
    lines = [doc.contact.name]
    if doc.contact.headline:
        lines.append(doc.contact.headline)
    lines.append(" | ".join(x for x in [doc.contact.email, doc.contact.phone, doc.contact.location, *doc.contact.links] if x))
    if doc.summary:
        lines += ["", "PROFESSIONAL SUMMARY", doc.summary]
    if doc.skills:
        lines += ["", "TECHNICAL SKILLS"] + [f"{g.name}: {', '.join(g.items)}" for g in doc.skills]
    if doc.experience:
        lines += ["", "PROFESSIONAL EXPERIENCE"]
        for e in doc.experience:
            lines.append(f"{e.title} | {e.company} | {e.location or ''} | {e.date_text}")
            lines += [f"• {b.text}" for b in e.bullets]
    if doc.projects:
        lines += ["", "PROJECTS"]
        for p in doc.projects:
            lines.append(p.name + (f" — {p.subtitle}" if p.subtitle else ""))
            if p.technologies:
                lines.append(" · ".join(p.technologies))
            lines += [f"• {b.text}" for b in p.bullets]
    if doc.education:
        lines += ["", "EDUCATION", *doc.education]
    if doc.certifications:
        lines += ["", "CERTIFICATIONS", *doc.certifications]
    for section in doc.extra_sections:
        lines += ["", section.title.upper(), *section.lines]
    return "\n".join(lines)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text) if s.strip()]


def tailor(
    master: ResumeDocument,
    parsed: ParsedJob,
    candidate: CandidateProfile,
    profile: Profile,
    *,
    role_family: str,
    max_bullets_older_roles: int = 4,
) -> TailorResult:
    rel = _Relevance(parsed, role_family)
    doc = master.model_copy(deep=True)
    doc.warnings = []
    result = TailorResult(document=doc, role_family=role_family)
    wanted = list(dict.fromkeys(parsed.required_skills + parsed.preferred_skills))

    # Headline: keep your own role label, then your strongest *verified* matching skills.
    matched = [s for s in wanted if candidate.has(s)]
    if master.contact.headline:
        label = re.split(r"\s+[·|—–-]\s+", master.contact.headline)[0].strip()
        if matched:
            doc.contact.headline = " · ".join([label, *matched[:6]])
            if doc.contact.headline != master.contact.headline:
                result.changes.append("Headline lists your verified skills that this job asks for")

    # Summary: identity sentence first, the rest by relevance.
    sentences = _sentences(master.summary)
    if len(sentences) > 2:
        head, rest = sentences[0], sentences[1:]
        ordered = sorted(rest, key=lambda s: -rel.score(s))
        if ordered != rest:
            doc.summary = " ".join([head, *ordered])
            result.changes.append("Summary sentences reordered to lead with what this job emphasises")

    # Skills: most relevant groups first; within a group, matched items first. Nothing removed.
    def group_score(g: SkillGroup) -> float:
        return sum(rel.score(i) for i in g.items)

    new_groups = []
    items_moved = False
    for g in sorted(master.skills, key=lambda g: -group_score(g)):
        items = sorted(g.items, key=lambda i: -rel.score(i))
        items_moved = items_moved or items != g.items
        new_groups.append(SkillGroup(name=g.name, items=items))
    if [g.name for g in new_groups] != [g.name for g in master.skills]:
        result.changes.append("Skill groups reordered by relevance to the job")
    if items_moved:
        result.changes.append("Matching skills moved to the front of each group")
    # Verified skills you added in the profile (with evidence) that the job wants but the resume lacks.
    in_resume = set(extract_skills(master.full_text()))
    extras = [x.name for x in profile.verified_extra_skills
              if any(s in wanted for s in (extract_skills(x.name) or [x.name])) and not set(extract_skills(x.name)) <= in_resume]
    if extras:
        new_groups.append(SkillGroup(name="Additional Skills", items=extras))
        result.changes.append(f"Added verified profile skills the job asks for: {', '.join(extras)}")
    doc.skills = new_groups

    # Experience: chronological order kept; bullets ordered by relevance; older roles trimmed.
    for i, entry in enumerate(doc.experience):
        original = list(entry.bullets)
        ordered = sorted(original, key=lambda b: -rel.score(b.text))
        keep: list[Bullet] = ordered
        if not entry.is_current and i > 0 and len(ordered) > max_bullets_older_roles:
            keep = ordered[:max_bullets_older_roles]
            for dropped in ordered[max_bullets_older_roles:]:
                result.omitted_bullets.append({"section": f"{entry.title} @ {entry.company}", "text": dropped.text})
        entry.bullets = keep
        if [b.id for b in keep] != [b.id for b in original]:
            result.changes.append(f"Bullets for '{entry.title}' reordered by relevance"
                                  + (f"; {len(original) - len(keep)} less relevant omitted" if len(keep) < len(original) else ""))

    # Projects: most relevant first.
    def project_score(p) -> float:  # noqa: ANN001
        return rel.score(" ".join([p.name, *p.technologies, *(b.text for b in p.bullets)]))

    ordered_projects = sorted(doc.projects, key=lambda p: -project_score(p))
    if [p.id for p in ordered_projects] != [p.id for p in doc.projects]:
        result.changes.append("Projects reordered by relevance")
    doc.projects = ordered_projects

    tailored_text = render_text(doc)
    present = set(extract_skills(tailored_text))
    result.keyword_coverage = {
        "covered": [s for s in wanted if s in present],
        "missing_not_in_profile": [s for s in wanted if s not in present and not candidate.has(s)],
        "missing_but_verified": [s for s in wanted if s not in present and candidate.has(s)],
    }
    result.diff = "\n".join(
        difflib.unified_diff(render_text(master).split("\n"), tailored_text.split("\n"), "master", "tailored", lineterm="")
    )
    if not result.changes:
        result.changes.append("No changes: the master resume already leads with what this job emphasises")
    return result

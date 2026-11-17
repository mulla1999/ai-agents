"""Profile intelligence: an evidence-based view of the candidate, built from the master resume.

A skill counts only if the resume mentions it (skills section, a bullet, a project) or you added it
as a verified extra skill with evidence. Years of experience are computed from the resume's dates,
never taken from a claim in the summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .domain import ExperienceEntry, Profile, ResumeDocument
from .skills import category_of, extract_skills


@dataclass
class Evidence:
    where: str  # "skills" | "experience:e1" | "project:p2" | "summary" | "profile"
    text: str


@dataclass
class CandidateProfile:
    name: str
    years_experience: float
    years_including_internships: float
    current_title: str | None
    current_company: str | None
    titles: list[str]
    skills: dict[str, list[Evidence]] = field(default_factory=dict)
    education: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    resume: ResumeDocument | None = None

    def has(self, skill: str) -> bool:
        return skill in self.skills

    def skills_in(self, category: str) -> list[str]:
        return [s for s in self.skills if category_of(s) == category]

    @property
    def has_cs_degree(self) -> bool:
        text = " ".join(self.education).lower()
        return any(k in text for k in ("computer", "b.tech", "b.e.", "btech", "information technology", "m.tech", "mca",
                                       "bca", "b.sc it", "software engineering", "computer science"))


def _months(entry: ExperienceEntry, today: date) -> tuple[date, date] | None:
    if entry.start is None:
        return None
    end = today if entry.is_current or entry.end is None else entry.end
    return entry.start, end


def experience_years(entries: list[ExperienceEntry], *, include_internships: bool, today: date | None = None) -> float:
    """Total years across roles, counting overlapping periods once. End months are inclusive."""
    today = today or date.today()
    spans = sorted(
        span
        for e in entries
        if (include_internships or not e.is_internship) and (span := _months(e, today)) is not None
    )
    months = 0
    current: tuple[int, int] | None = None
    for start, end in spans:
        a, b = start.year * 12 + start.month - 1, end.year * 12 + end.month - 1
        if current is None or a > current[1] + 1:
            if current is not None:
                months += current[1] - current[0] + 1
            current = (a, b)
        else:
            current = (current[0], max(current[1], b))
    if current is not None:
        months += current[1] - current[0] + 1
    return round(months / 12, 1)


def build_candidate(resume: ResumeDocument, profile: Profile, today: date | None = None) -> CandidateProfile:
    skills: dict[str, list[Evidence]] = {}

    def add(text: str, where: str) -> None:
        for skill in extract_skills(text):
            skills.setdefault(skill, []).append(Evidence(where, text))

    for group in resume.skills:
        for item in group.items:
            add(item, "skills")
    for entry in resume.experience:
        for bullet in entry.bullets:
            add(bullet.text, f"experience:{entry.id}")
    for project in resume.projects:
        add(" · ".join(project.technologies), f"project:{project.id}")
        for bullet in project.bullets:
            add(bullet.text, f"project:{project.id}")
    add(resume.summary, "summary")
    for extra in profile.verified_extra_skills:
        names = extract_skills(extra.name) or [extra.name.strip()]
        for name in names:
            skills.setdefault(name, []).append(Evidence("profile", extra.evidence))

    current = next((e for e in resume.experience if e.is_current), resume.experience[0] if resume.experience else None)
    professional = experience_years(resume.experience, include_internships=False, today=today)
    with_interns = experience_years(resume.experience, include_internships=True, today=today)
    return CandidateProfile(
        name=profile.full_name or resume.contact.name,
        years_experience=with_interns if profile.count_internships_as_experience else professional,
        years_including_internships=with_interns,
        current_title=current.title if current else None,
        current_company=current.company if current else None,
        titles=[e.title for e in resume.experience],
        skills=skills,
        education=resume.education,
        certifications=resume.certifications,
        resume=resume,
    )

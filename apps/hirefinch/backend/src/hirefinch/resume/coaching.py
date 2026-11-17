"""Resume coaching: a deterministic health check and the writing rules the AI follows.

The bullet formula (X-Y-Z), action-verb groups and tech-resume advice are distilled from the
MIT-licensed "Resume Skills" collection (https://github.com/paramchoudhary/resumeskills; see
THIRD_PARTY_NOTICES.md). One deliberate difference: that collection suggests estimating numbers when
the real ones are unknown. HireFinch never does; it asks the person for the real figure instead.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ..domain import ResumeDocument
from .validator import numbers_in

# Strong openings, grouped as the collection groups them; used in the AI rules and in tips.
ACTION_VERBS: dict[str, tuple[str, ...]] = {
    "built": ("Built", "Developed", "Designed", "Implemented", "Created", "Launched", "Shipped"),
    "improved": ("Improved", "Optimised", "Reduced", "Accelerated", "Streamlined", "Automated", "Scaled"),
    "fixed": ("Resolved", "Debugged", "Diagnosed", "Stabilised", "Migrated", "Refactored"),
    "worked with others": ("Collaborated", "Partnered", "Coordinated", "Presented", "Documented"),
}

# Openings that describe duties, not results.
_WEAK_START = re.compile(
    r"^(responsible for|duties (included|include)|worked on|working on|helped|helping|assisted|involved in|"
    r"participated in|tasked with|in charge of|handled|did|was|were)\b", re.I)
_FIRST_PERSON = re.compile(r"\b(I|me|my|we|our)\b")

# Rules for any AI step that writes resume text. Kept short: they are sent with every request.
BULLET_RULES = (
    "Write each bullet as one sentence following the X-Y-Z pattern where the facts allow: what was accomplished "
    "(X), how it was measured (Y), and how it was done (Z), e.g. 'Cut API latency 40% by adding Redis caching to "
    "the order service'. Start with a specific past-tense action verb (Built, Designed, Reduced, Automated, "
    "Migrated, Resolved, Improved), never 'Responsible for', 'Worked on' or 'Helped'. Put the result and the key "
    "technology early. Prefer concrete nouns over adjectives; no buzzwords ('synergy', 'passionate', "
    "'dynamic'), no first person, no trailing full stop."
)


@dataclass
class Tip:
    level: str  # "fix" (hurts the resume) | "improve" (would make it stronger)
    section: str
    message: str
    target: str | None = None  # a bullet or entry id, so the page can point at it
    kind: str | None = None  # the same problem on several bullets shares a kind, and is scored as one


@dataclass
class HealthReport:
    score: int
    tips: list[Tip] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"score": self.score, "tips": [asdict(t) for t in self.tips]}


def review(doc: ResumeDocument) -> HealthReport:
    """What a recruiter or an ATS would trip over, most important first. Purely rule-based, so the
    same resume always gets the same score."""
    tips: list[Tip] = []
    c = doc.contact
    if not c.name.strip():
        tips.append(Tip("fix", "contact", "Add your full name."))
    if not c.email:
        tips.append(Tip("fix", "contact", "Add an email address: recruiters need a way to reply."))
    if not c.phone:
        tips.append(Tip("improve", "contact", "Add a phone number; many recruiters call first."))
    if not any("linkedin" in link.lower() for link in c.links):
        tips.append(Tip("improve", "contact", "Add your LinkedIn profile link."))

    words = len(doc.summary.split())
    if words == 0:
        tips.append(Tip("improve", "summary", "Add a 2–3 sentence summary: your role, years of experience and strongest skills."))
    elif words > 90:
        tips.append(Tip("improve", "summary", f"Shorten the summary to under 90 words (now {words})."))

    skills = sum(len(g.items) for g in doc.skills)
    if skills == 0:
        tips.append(Tip("fix", "skills", "Add a Skills section: applicant tracking systems match on it first."))
    elif skills < 6:
        tips.append(Tip("improve", "skills", "List more of the tools and technologies you really use (at least 6)."))

    if not doc.experience and not doc.projects:
        tips.append(Tip("fix", "experience", "Add your work experience, or projects if you are starting out."))
    for entry in doc.experience:
        label = f"{entry.title or 'Role'} at {entry.company or '…'}"
        if not entry.title.strip() or not entry.company.strip():
            tips.append(Tip("fix", "experience", f"{label}: add both the job title and the company.", entry.id, "role_fields"))
        if not entry.date_text.strip() and entry.start is None:
            tips.append(Tip("fix", "experience", f"{label}: add the dates you worked there.", entry.id, "role_dates"))
        if len(entry.bullets) < 2:
            tips.append(Tip("improve", "experience", f"{label}: add 2–5 bullets about what you achieved.", entry.id, "few_bullets"))
        elif len(entry.bullets) > 7:
            tips.append(Tip("improve", "experience", f"{label}: keep the 5–6 strongest bullets.", entry.id, "many_bullets"))

    bullets = doc.all_bullets()
    measured = 0
    for b in bullets:
        text = b.text.strip()
        if not text:
            continue
        if numbers_in(text):
            measured += 1
        if _WEAK_START.match(text):
            first = " ".join(text.split()[:2])
            tips.append(Tip("fix", "bullets", f"“{first}…” describes a duty. Start with what you did: Built, Reduced, Automated…", b.id, "duty"))
        if _FIRST_PERSON.search(text):
            tips.append(Tip("fix", "bullets", "Leave out “I”, “my” and “we”: resumes are written without them.", b.id, "first_person"))
        if len(text) > 230:
            tips.append(Tip("improve", "bullets", "This bullet is long; aim for one or two lines.", b.id, "long"))
    filled = [b for b in bullets if b.text.strip()]
    if filled and measured < max(1, len(filled) // 3):
        tips.append(Tip("improve", "bullets",
                        f"Only {measured} of {len(filled)} bullets show a result in numbers. Use “Make it measurable” to add real figures."))

    if not doc.education:
        tips.append(Tip("improve", "education", "Add your education (degree, college, year)."))

    return HealthReport(score(tips), sorted(tips, key=lambda t: t.level != "fix"))


def score(tips: list[Tip]) -> int:
    """100 minus a penalty per *kind* of problem: the first time it appears it costs fully (12 for a fix,
    4 for an improvement), each repeat a little more (3 / 1), up to a cap (21 / 7). So "we" in four
    bullets is one habit to fix, not four separate failures."""
    groups: dict[str, list[Tip]] = {}
    for t in tips:
        groups.setdefault(f"{t.level}:{t.kind or t.message}", []).append(t)
    penalty = 0
    for items in groups.values():
        first, extra, cap = (12, 3, 21) if items[0].level == "fix" else (4, 1, 7)
        penalty += min(cap, first + extra * (len(items) - 1))
    return max(0, min(100, 100 - penalty))

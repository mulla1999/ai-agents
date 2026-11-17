"""Resume Builder: turn a resume written on the site into a master resume.

The page sends the structured resume (the same ``ResumeDocument`` an upload is parsed into). It is
checked, rendered with the same ATS-safe renderer as tailored resumes, and stored as a master, so
matching and tailoring work from it exactly as from an uploaded file. AI help only suggests text:
every suggestion goes through the same fact checks as tailoring before it is shown.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import asdict
import os
import stat
import tempfile
from datetime import date
from pathlib import Path

from agents_core.llm import LLMError, LLMProvider
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import llm_assist
from ..config import Settings
from ..db import ResumeMaster
from ..domain import ResumeDocument, SkillGroup
from ..errors import ServiceError
from ..resume.coaching import review
from ..resume.render import render_resume
from ..resume.tailor import render_text
from ..resume.validator import numbers_in, rewrite_problem
from ..skills import category_of, extract_skills
from ..text import resume_filename
from .audit import record

# Generous for a real resume, small enough that nobody can use the renderer as a free PDF farm.
LIMITS = {"experience": 15, "projects": 12, "bullets": 10, "text": 400, "summary": 1200, "list": 40}
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def _month(d: date | None) -> str:
    return f"{_MONTHS[d.month - 1]} {d.year}" if d else ""


def prepare(doc: ResumeDocument, *, limits: bool = True) -> ResumeDocument:
    """Check limits, fill in printed dates from the month pickers, give every entry and bullet an id,
    and drop empty bullets. Raises a ServiceError the page can show. ``limits=False`` (for checks on a
    draft) skips the size limits but still caps the work at sane maxima."""
    doc = doc.model_copy(deep=True)
    if not limits:
        doc.experience, doc.projects = doc.experience[:30], doc.projects[:30]
        for entry in [*doc.experience, *doc.projects]:
            entry.bullets = entry.bullets[:30]
    if limits and (len(doc.experience) > LIMITS["experience"] or len(doc.projects) > LIMITS["projects"]):
        raise ServiceError("too_long", "that is more entries than a resume can hold; keep the most relevant ones", 422)
    if limits and len(doc.summary) > LIMITS["summary"]:
        raise ServiceError("too_long", "the summary is too long; keep it under 90 words", 422)
    for n, entry in enumerate([*doc.experience, *doc.projects]):
        entry.id = entry.id or f"e{n + 1}"
        entry.bullets = [b for b in entry.bullets if b.text.strip()]
        if limits and len(entry.bullets) > LIMITS["bullets"]:
            raise ServiceError("too_long", f"keep at most {LIMITS['bullets']} bullets per entry", 422)
        for m, b in enumerate(entry.bullets):
            b.id, b.text = b.id or f"{entry.id}b{m + 1}", " ".join(b.text.split())
            if limits and len(b.text) > LIMITS["text"]:
                raise ServiceError("too_long", "a bullet is too long; keep each to one or two lines", 422)
    for entry in doc.experience:
        if entry.start and entry.end and entry.end < entry.start:
            raise ServiceError("bad_dates", f"{entry.title} at {entry.company}: the end date is before the start date", 422)
        if not entry.date_text.strip() and entry.start:
            entry.date_text = f"{_month(entry.start)} – {'Present' if entry.is_current else _month(entry.end)}"
    for name in ("education", "certifications"):
        values = [" ".join(v.split()) for v in getattr(doc, name) if v.strip()]
        if limits and len(values) > LIMITS["list"]:
            raise ServiceError("too_long", f"too many {name} lines", 422)
        setattr(doc, name, values)
    doc.skills = [g for g in doc.skills if g.items]
    doc.warnings = []
    return doc


def render_pdf(doc: ResumeDocument) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        pdf, docx = Path(tmp) / "resume.pdf", Path(tmp) / "resume.docx"
        render_resume(doc, docx, pdf)
        return pdf.read_bytes()


async def save(db: AsyncSession, settings: Settings, user_id: int, doc: ResumeDocument, *, max_resumes: int = 50) -> ResumeMaster:
    """Store the built resume as a master and make it the one in use."""
    doc = prepare(doc)
    if not doc.contact.name.strip() or not (doc.experience or doc.projects):
        raise ServiceError("incomplete", "add at least your name and one job or project before saving", 422)
    data = render_pdf(doc)
    digest = hashlib.sha256(data).hexdigest()
    master = await db.scalar(select(ResumeMaster).where(ResumeMaster.user_id == user_id, ResumeMaster.sha256 == digest))
    if master is not None:
        master.archived_at = None
    else:
        count = await db.scalar(select(func.count(ResumeMaster.id)).where(ResumeMaster.user_id == user_id,
                                                                          ResumeMaster.archived_at.is_(None)))
        if (count or 0) >= max_resumes:
            raise ServiceError("limit", f"you can keep up to {max_resumes} resumes; delete one first", 409)
        folder = settings.data_dir / "masters" / str(user_id)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{digest[:16]}.pdf"
        if not target.exists():
            target.write_bytes(data)
            os.chmod(target, stat.S_IRUSR | stat.S_IRGRP)
        master = ResumeMaster(user_id=user_id, filename=resume_filename(doc.contact.name), file_path=str(target),
                              file_format="pdf", sha256=digest, parsed=doc.model_dump(mode="json"), is_active=False)
        db.add(master)
        await db.flush()
    await db.execute(update(ResumeMaster).where(ResumeMaster.user_id == user_id).values(is_active=False))
    master.is_active = True
    await record(db, user_id, "resume.built", "resume saved from the Resume Builder", actor="user",
                 entity=("resume_master", master.id), details={"sha256": digest})
    return master


def _needs_ai(llm: LLMProvider | None) -> LLMProvider:
    if llm is None:
        raise ServiceError("ai_not_configured", "connect an AI provider in Integrations to use writing help", 409)
    return llm


async def improve_bullet(llm: LLMProvider | None, text: str, role: str, facts: str = "") -> dict[str, str]:
    """A checked suggestion. Numbers and technologies may come only from the bullet and the person's facts."""
    text, facts = " ".join(text.split()), " ".join(facts.split())
    if len(text) < 8:
        raise ServiceError("too_short", "write a few words about what you did first", 422)
    try:
        out = await llm_assist.improve_bullet(_needs_ai(llm), text, role, facts)
    except LLMError as exc:
        raise ServiceError("ai_failed", f"the AI couldn't help right now ({exc})", 502) from exc
    problem = rewrite_problem(text, out["text"], facts, draft=True)
    if problem and problem != "unchanged":
        return {"text": "", "question": out["question"], "rejected": f"The suggestion was not used: it {problem}."}
    return {"text": out["text"], "question": out["question"], "rejected": ""}


async def write_summary(llm: LLMProvider | None, doc: ResumeDocument) -> str:
    text = render_text(prepare(doc))
    try:
        summary = await llm_assist.write_summary(_needs_ai(llm), text)
    except LLMError as exc:
        raise ServiceError("ai_failed", f"the AI couldn't help right now ({exc})", 502) from exc
    if not numbers_in(summary) <= numbers_in(text) or not set(extract_skills(summary)) <= set(extract_skills(text)):
        raise ServiceError("ai_failed", "the suggested summary mentioned something not on your resume, so it was not used; try again", 502)
    return summary


# ---------------------------------------------------------------- fix all

_CATEGORY_NAMES = {"language": "Languages", "backend": "Backend", "frontend": "Frontend", "ai": "AI & ML", "cloud": "Cloud",
                   "devops": "DevOps", "data": "Databases & Data", "testing": "Testing", "practice": "Practices"}


def skills_from_resume(doc: ResumeDocument) -> list[SkillGroup]:
    """A grouped Skills section from technologies the resume itself already names (bullets, projects,
    summary), merged with any skills already listed. Nothing new is claimed: each one is on the page."""
    text = " ".join([doc.summary, *(b.text for b in doc.all_bullets()), *(t for p in doc.projects for t in p.technologies)])
    found = list(dict.fromkeys([*(i for g in doc.skills for i in g.items), *extract_skills(text)]))
    groups: dict[str, list[str]] = {}
    for name in found:
        groups.setdefault(_CATEGORY_NAMES.get(category_of(name) or "", "Other"), []).append(name)
    order = [*_CATEGORY_NAMES.values(), "Other"]
    return [SkillGroup(name=n, items=groups[n]) for n in order if groups.get(n)]


MAX_BULLETS = 6  # per role, after "Fix all": recruiters skim, so the strongest six carry a role


def _strength(text: str) -> tuple[int, int, int]:
    """How much a bullet shows: results in numbers, then technologies, then substance."""
    return (len(numbers_in(text)), len(extract_skills(text)), min(len(text), 200))


async def _rewrite_flagged(llm: LLMProvider, flagged: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Checked rewrites by id, plus why the rest were rejected. A rejected rewrite gets one more try,
    told exactly what failed (e.g. "drops technologies: Event-Driven Architecture")."""
    accepted: dict[str, str] = {}
    rejected: dict[str, str] = {}
    attempt: dict[str, str] = {}
    for _ in range(2):
        pending = [i for i in flagged if i not in accepted]
        if not pending:
            break
        items = [{"id": i, "text": flagged[i], **({"previous_attempt": attempt[i], "rejected_because": rejected[i]} if i in rejected else {})}
                 for i in pending]
        for bid, text in (await llm_assist.fix_bullets(llm, items)).items():
            problem = rewrite_problem(flagged[bid], text, shorten=len(flagged[bid]) > 230)
            if problem is None:
                accepted[bid] = text
                rejected.pop(bid, None)
            else:
                attempt[bid], rejected[bid] = text, problem
    return accepted, rejected


async def fix_all(llm: LLMProvider | None, doc: ResumeDocument) -> dict:
    """Everything the resume check flags that can be fixed without new facts, as a list of changes the
    page shows (each can be unticked) before applying. Nothing is saved here.

    Without AI: a Skills section from what the resume already names, and long roles trimmed to their
    strongest bullets. With AI: duty phrases, first person and overlong bullets rewritten (each checked
    like a tailored bullet, with one retry), and a missing or overlong summary rewritten."""
    doc = doc.model_copy(deep=True)
    for entry in [*doc.experience, *doc.projects]:
        entry.bullets = [b for b in entry.bullets if b.text.strip()]
    before = review(doc)
    changes: list[dict] = []

    if sum(len(g.items) for g in doc.skills) < 6:
        rebuilt = skills_from_resume(doc)
        if sum(len(g.items) for g in rebuilt) > sum(len(g.items) for g in doc.skills):
            changes.append({"op": "skills", "section": "skills", "before": "", "groups": [g.model_dump() for g in rebuilt],
                            "after": "; ".join(f"{g.name}: {', '.join(g.items)}" for g in rebuilt)})
            doc.skills = rebuilt

    by_id = {b.id: b for b in doc.all_bullets()}
    flagged = {t.target: by_id[t.target].text for t in before.tips if t.section == "bullets" and t.target in by_id}
    words = len(doc.summary.split())
    wants_summary = llm is not None and (words == 0 or words > 90) and bool(doc.experience or doc.projects)
    notes: list[str] = []

    # The AI calls run at once, so the request stays well inside the ~100 s a proxy allows.
    async def bullets() -> tuple[dict[str, str], dict[str, str]]:
        return await _rewrite_flagged(llm, flagged) if llm is not None and flagged else ({}, {})

    async def summary() -> str | None:
        return await write_summary(llm, doc) if wants_summary else None

    rewritten, new_summary = await asyncio.gather(bullets(), summary(), return_exceptions=True)
    if isinstance(rewritten, BaseException):
        notes.append(f"AI help wasn't available ({_why(rewritten)}).")
        rewritten = ({}, {})
    accepted, rejected = rewritten
    for bid, text in accepted.items():
        changes.append({"op": "bullet", "section": "bullet", "id": bid, "before": by_id[bid].text, "after": text})
        by_id[bid].text = text
    if rejected:
        many = len(rejected) > 1
        notes.append(f"{len(rejected)} bullet{'s' if many else ''} kept as written: the AI's version changed a fact. "
                     f"Use Improve on {'them' if many else 'it'} to try again.")
    if isinstance(new_summary, BaseException):
        notes.append(f"The summary couldn't be rewritten ({_why(new_summary)}).")
    elif new_summary:
        changes.append({"op": "summary", "section": "summary", "before": doc.summary, "after": new_summary})
        doc.summary = new_summary

    for entry in doc.experience:
        if len(entry.bullets) > MAX_BULLETS + 1:
            keep = {b.id for b in sorted(entry.bullets, key=lambda b: _strength(b.text), reverse=True)[:MAX_BULLETS]}
            for b in entry.bullets:
                if b.id not in keep:
                    changes.append({"op": "remove", "section": f"remove from {entry.title}", "id": b.id, "before": b.text, "after": ""})
            entry.bullets = [b for b in entry.bullets if b.id in keep]

    if llm is None:
        notes.append("Connect an AI provider in Integrations to also fix bullet wording and the summary.")
    after = review(doc)
    return {"document": doc.model_dump(mode="json"), "changes": changes, "score_before": before.score,
            "score_after": after.score, "remaining": [asdict(t) for t in after.tips], "note": " ".join(notes)}

def _why(exc: BaseException) -> str:
    return exc.message if isinstance(exc, ServiceError) else str(exc)

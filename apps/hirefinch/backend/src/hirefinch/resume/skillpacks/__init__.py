"""Installed writing skills for the AI provider.

The SKILL.md guides in this folder come from the MIT-licensed "Resume Skills" collection, pinned to one
commit (manifest.json, with a SHA-256 per file; LICENSE alongside). Any provider can use them: for each
task, ``guide(task)`` returns only the sections that matter, sent as reference material with the request.

Two safety rules apply on top of the guides:
* A file whose checksum doesn't match the manifest is ignored (and logged), so an edited or corrupted
  guide never reaches a prompt.
* Advice to estimate or approximate numbers is removed: HireFinch never states a figure the person
  didn't give, and every AI output is still checked against the resume facts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)
_DIR = Path(__file__).parent

# Which ## sections of which guide each task uses. Kept small: they are sent with every request.
TASKS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "bullets": [
        ("resume-bullet-writer.md", ("Core Frameworks", "Power Verbs by Category", "Common Bullet Writing Mistakes",
                                     "Bullet Strength Checklist")),
        ("tech-resume-optimizer.md", ("Experience Section for Tech Roles",)),
    ],
    "summary": [
        ("resume-section-builder.md", ("Professional Summary Section",)),
        ("tech-resume-optimizer.md", ("Tech Resume Philosophy",)),
    ],
    "skills": [
        ("resume-section-builder.md", ("Skills Section",)),
        ("tech-resume-optimizer.md", ("Technical Skills Section",)),
    ],
    "ats": [
        ("resume-ats-optimizer.md", ("ATS Compatibility Checklist", "Common ATS Failure Patterns")),
    ],
    "interview": [
        ("interview-prep-generator.md", ("The STAR Method Detailed", "Story Banking Process", "Questions to Ask Interviewers",
                                         "Handling Difficult Questions")),
    ],
}
MAX_CHARS = 7000  # per task
# Sub-sections left out entirely, and lines dropped wherever they appear.
_SKIP_SUBSECTIONS = ("When You Don't Have Exact Numbers", "Salary Questions")
_SKIP_LINE = re.compile(r"\b(estimat\w*|approximat\w*|ballpark|round (?:up|down))\b|~\s*\d", re.I)


@lru_cache
def _verified() -> dict[str, str]:
    """File name -> text, for the files whose checksum matches the manifest."""
    try:
        manifest = json.loads((_DIR / "manifest.json").read_text())
    except (OSError, ValueError):
        log.warning("skill packs: manifest missing or unreadable; AI requests use built-in rules only")
        return {}
    out: dict[str, str] = {}
    for name, digest in manifest.get("files", {}).items():
        path = _DIR / name
        try:
            data = path.read_bytes()
        except OSError:
            log.warning("skill packs: %s is missing", name)
            continue
        if hashlib.sha256(data).hexdigest() != digest:
            log.warning("skill packs: %s does not match its pinned checksum and is ignored", name)
            continue
        out[name] = data.decode("utf-8")
    return out


def _sections(text: str, wanted: tuple[str, ...]) -> list[str]:
    parts = re.split(r"(?m)^(?=## )", text)
    chosen = []
    for part in parts:
        title = part.split("\n", 1)[0].removeprefix("## ").strip()
        if title in wanted:
            chosen.append(_clean(part))
    return chosen


def _clean(section: str) -> str:
    keep, skipping = [], False
    for line in section.splitlines():
        if line.startswith("### "):
            skipping = line.removeprefix("### ").strip() in _SKIP_SUBSECTIONS
        if skipping or _SKIP_LINE.search(line):
            continue
        keep.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip()


@lru_cache
def guide(task: str) -> str:
    """Reference material for ``task`` ("bullets", "summary", "skills", "ats", "interview"), or "" if none
    could be loaded. Wrapped in a tag so prompts can say it is guidance, not facts about the person."""
    files = _verified()
    chunks: list[str] = []
    for name, wanted in TASKS.get(task, []):
        if name in files:
            chunks += _sections(files[name], wanted)
    text = "\n\n".join(chunks)[:MAX_CHARS]
    return f"<writing_guide>\n{text}\n</writing_guide>" if text else ""


def status() -> dict[str, object]:
    """For the admin page: which guides are installed and verified."""
    manifest = json.loads((_DIR / "manifest.json").read_text()) if (_DIR / "manifest.json").exists() else {}
    files = _verified()
    return {"source": manifest.get("source"), "commit": manifest.get("commit"),
            "installed": sorted(files), "tasks": {t: bool(guide(t)) for t in TASKS}}

"""Duplicate detection. Pure functions; the ingest service supplies the candidate rows.

Order of evidence, strongest first:
1. same source and source job id  -> the same posting (update it)
2. same canonical URL             -> the same posting seen through another source
3. same company + normalised title + location, with a near-identical description
                                  -> duplicate (cross-posted)
4. same company + title, description differs or posted 30+ days later
                                  -> repost: kept as its own row, linked and flagged
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from ..text import jaccard, normalize, shingles

DUPLICATE_SIMILARITY = 0.8
REPOST_DAYS = 30


class Existing(Protocol):
    id: int
    canonical_url: str
    normalized_company: str
    normalized_title: str
    location: str | None
    description_text: str
    posted_at: date | None
    duplicate_of_id: int | None


@dataclass
class Verdict:
    kind: Literal["new", "same_url", "duplicate", "repost"]
    job_id: int | None = None
    similarity: float = 0.0


def similarity(a: str, b: str) -> float:
    return jaccard(shingles(a), shingles(b))


def classify(
    *,
    canonical_url: str,
    normalized_company: str,
    normalized_title: str,
    location: str | None,
    description_text: str,
    posted_at: date | None,
    candidates: list[Existing],
) -> Verdict:
    for row in candidates:
        if row.canonical_url == canonical_url:
            return Verdict("same_url", row.id, 1.0)
    same_role = [
        r for r in candidates
        if r.normalized_company == normalized_company and r.normalized_title == normalized_title
    ]
    if not same_role:
        return Verdict("new")
    best: Verdict = Verdict("new")
    for row in same_role:
        root = row.duplicate_of_id or row.id
        sim = similarity(description_text, row.description_text)
        same_place = normalize(row.location or "") == normalize(location or "") or not row.location or not location
        late = bool(posted_at and row.posted_at and (posted_at - row.posted_at).days >= REPOST_DAYS)
        if sim >= DUPLICATE_SIMILARITY and same_place and not late:
            if best.kind != "duplicate" or sim > best.similarity:
                best = Verdict("duplicate", root, sim)
        elif same_place and best.kind == "new":
            best = Verdict("repost", root, sim)
    return best

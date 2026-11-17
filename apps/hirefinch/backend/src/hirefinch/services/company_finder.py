"""Find a company's job board from its name or careers link, so it can be added as a source.

Greenhouse, Lever, Ashby and SmartRecruiters publish each employer's openings through an official,
public API keyed by a board id ("stripe", "cred"). A company name is turned into a few likely ids and
each system is asked whether that board exists: a handful of small read-only requests, nothing else.
A careers link on one of those systems names its board directly.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

from ..net import MAX_BOARD_BYTES, FetchError, SafeFetcher

KINDS = ("greenhouse", "lever", "ashby", "smartrecruiters")
_HOSTS = {"boards-api.greenhouse.io", "api.lever.co", "api.ashbyhq.com", "api.smartrecruiters.com"}
_LINK_HOSTS = {
    "boards.greenhouse.io": "greenhouse", "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever", "jobs.ashbyhq.com": "ashby",
    "jobs.smartrecruiters.com": "smartrecruiters", "careers.smartrecruiters.com": "smartrecruiters",
}
_TOKEN = re.compile(r"[A-Za-z0-9_.-]{1,80}")
# Words companies drop from their board id ("Razorpay Software Pvt Ltd" -> "razorpay").
_SUFFIXES = re.compile(r"\b(pvt|private|ltd|limited|inc|llc|llp|corp|corporation|co|technologies|technology|"
                       r"solutions|software|labs|india|group|the)\b")
_INDIA = ("india", "bengaluru", "bangalore", "mumbai", "pune", "hyderabad", "chennai", "gurgaon", "gurugram",
          "noida", "delhi", "kolkata", "ahmedabad", "kochi", "remote - in", "remote, in")


@dataclass
class Board:
    kind: str
    token: str
    company: str
    jobs: int
    india_jobs: int | None  # None when the system's summary does not list locations


def _india(locations: list[str]) -> int:
    return sum(1 for loc in locations if any(w in (loc or "").lower() for w in _INDIA))


def candidates(query: str) -> tuple[list[str], str | None]:
    """Likely board ids for a name, or the one board a careers link names (then its system too)."""
    text = query.strip()
    if "://" in text or text.split("/")[0].count(".") >= 1:
        parts = urlsplit(text if "://" in text else "https://" + text)
        kind = _LINK_HOSTS.get((parts.hostname or "").lower())
        path = [p for p in parts.path.split("/") if p]
        if kind and path and _TOKEN.fullmatch(path[0]):
            return [path[0]], kind
        # Any other link or a name like "Booking.com": search by the site's name.
        host = (parts.hostname or "").lower().removeprefix("www.").removeprefix("careers.").removeprefix("jobs.")
        text = host.split(".")[0] if host else text
    words = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()
    core = _SUFFIXES.sub(" ", " ".join(words)).split() or words
    out: list[str] = []
    for c in ("".join(core), "-".join(core), "".join(words), core[0] if core else ""):
        if c and _TOKEN.fullmatch(c) and c not in out:
            out.append(c)
    return out[:3], None


async def _probe(fetcher: SafeFetcher, kind: str, token: str) -> Board | None:
    try:
        if kind == "greenhouse":
            r = await fetcher.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", max_bytes=MAX_BOARD_BYTES)
            if r.status_code != 200:
                return None
            jobs = r.json().get("jobs") or []
            name = (jobs[0].get("company_name") if jobs else None) or token
            about = await fetcher.get(f"https://boards-api.greenhouse.io/v1/boards/{token}")
            if about.status_code == 200:
                name = about.json().get("name") or name
            return Board(kind, token, name, len(jobs), _india([(j.get("location") or {}).get("name", "") for j in jobs]))
        if kind == "lever":
            r = await fetcher.get(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"}, max_bytes=MAX_BOARD_BYTES)
            if r.status_code != 200 or not isinstance(r.json(), list):
                return None
            jobs = r.json()
            return Board(kind, token, token, len(jobs), _india([(j.get("categories") or {}).get("location", "") for j in jobs]))
        if kind == "ashby":
            r = await fetcher.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}", max_bytes=MAX_BOARD_BYTES)
            if r.status_code != 200:
                return None
            jobs = r.json().get("jobs") or []
            places = [" ".join([j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []])
                      for j in jobs]
            return Board(kind, token, token, len(jobs), _india(places))
        r = await fetcher.get(f"https://api.smartrecruiters.com/v1/companies/{token}/postings", params={"limit": "100"})
        if r.status_code != 200:
            return None
        body: dict[str, Any] = r.json()
        total = int(body.get("totalFound") or 0)
        if not total:
            return None  # SmartRecruiters answers every name; no postings means no board
        postings = body.get("content") or []
        name = ((postings[0].get("company") or {}).get("name") if postings else None) or token
        india = sum(1 for p in postings if ((p.get("location") or {}).get("country") or "").lower() == "in")
        return Board(kind, token, name, total, india if total <= len(postings) else None)
    except (FetchError, ValueError, AttributeError):
        return None  # unreachable, not JSON or an unexpected shape: treated as not found


async def find(fetcher: SafeFetcher, query: str) -> list[dict]:
    tokens, only = candidates(query)
    f = fetcher.with_hosts(_HOSTS)
    probes = [_probe(f, kind, token) for token in tokens for kind in ((only,) if only else KINDS)]
    found = [b for b in await asyncio.gather(*probes) if b is not None]
    # A name typed by the person reads better than a lowercase id when the API gives no display name.
    pretty = " ".join(w.capitalize() if w.islower() else w for w in query.split()) if not only else None
    for b in found:
        if b.company == b.token:
            b.company = pretty or b.token.replace("-", " ").title()
    return [asdict(b) for b in sorted(found, key=lambda b: (-(b.india_jobs or 0), -b.jobs))]

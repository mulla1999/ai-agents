"""Web search for job postings, through a licensed search API with the user's own key.

Brave Search API and Tavily are supported. Google, Bing and the like are never scraped. The search
favours employer career pages and the public ATS boards (Greenhouse, Lever, Ashby,
SmartRecruiters), whose postings ``job_fetch`` can read. Results on boards that do not allow
automated reading (LinkedIn, Naukri, Indeed...) are still shown as links for you to open, but the
agent does not fetch them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from ..errors import ServiceError
from ..net import FetchError, SafeFetcher
from .job_fetch import _blocked_site, _board

ATS_SITES = ("boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com",
             "jobs.smartrecruiters.com")
BRAVE = "https://api.search.brave.com/res/v1/web/search"
TAVILY = "https://api.tavily.com/search"


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    fetchable: bool  # the agent may read it (ATS board or a career page not on the no-automation list)
    ats: bool

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def build_query(role: str, location: str | None, ats_only: bool) -> str:
    sites = " OR ".join(f"site:{s}" for s in ATS_SITES)
    base = " ".join(x for x in [role.strip(), (location or "").strip(), "job"] if x)
    return f"{base} ({sites})" if ats_only else f"{base} careers apply"


def _hit(title: str, url: str, snippet: str) -> SearchHit | None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return None
    blocked = _blocked_site(parts.hostname.lower())
    return SearchHit(title=title.strip()[:200], url=url, snippet=" ".join(snippet.split())[:300],
                     fetchable=not blocked, ats=_board(url) is not None)


async def search_jobs(fetcher: SafeFetcher, creds: dict[str, Any] | None, role: str, location: str | None = None, *,
                      days: int = 7, ats_only: bool = True, limit: int = 10) -> list[SearchHit]:
    if not creds or not creds.get("api_key"):
        raise ServiceError("not_configured", "web search is not set up: add a Brave Search or Tavily key in Integrations", 409)
    query = build_query(role, location, ats_only)
    try:
        if creds.get("provider") == "tavily":
            response = await fetcher.with_hosts({"api.tavily.com"}).post_json(TAVILY, {
                "api_key": creds["api_key"], "query": query, "max_results": min(limit, 20), "days": days,
                "search_depth": "basic", "topic": "general"})
            if response.status_code in (401, 403):
                raise ServiceError("bad_key", "the Tavily key was rejected", 409)
            items = [(r.get("title", ""), r.get("url", ""), r.get("content", "")) for r in response.json().get("results", [])]
        else:
            freshness = "pd" if days <= 1 else "pw" if days <= 7 else "pm"
            response = await fetcher.with_hosts({"api.search.brave.com"}).get(
                BRAVE, params={"q": query, "count": min(limit, 20), "freshness": freshness},
                headers={"X-Subscription-Token": creds["api_key"]})
            if response.status_code in (401, 403, 422):
                raise ServiceError("bad_key", "the Brave Search key was rejected", 409)
            items = [(r.get("title", ""), r.get("url", ""), r.get("description", ""))
                     for r in (response.json().get("web") or {}).get("results", [])]
    except FetchError as exc:
        raise ServiceError("search_failed", f"web search failed: {exc}", 502) from exc
    if response.status_code >= 400:
        raise ServiceError("search_failed", f"web search answered HTTP {response.status_code}", 502)
    hits, seen = [], set()
    for title, url, snippet in items:
        hit = _hit(str(title), str(url), str(snippet))
        if hit and hit.url not in seen:
            seen.add(hit.url)
            hits.append(hit)
    return hits[:limit]

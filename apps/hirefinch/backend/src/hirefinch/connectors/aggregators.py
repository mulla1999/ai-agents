"""Broad keyword search through aggregators that publish official APIs for this use.

* Jooble (``jooble.org/api/<key>``): partner API with Indian coverage; needs a free key.
* The Muse (``www.themuse.com/api/public/jobs``): public API, mostly US/remote roles. Listings keep
  The Muse as the source and link back to its job page, as its terms ask.

Not included on purpose: Remotive, whose terms forbid showing its jobs behind a sign-up.
Every search is limited to the recency window (default: published in the last 3 days).
"""

from __future__ import annotations

import re

from ..domain import RawJob
from ..net import FetchError
from .ats import _date
from .base import Connector, ConnectorAuthError, ConnectorError, FetchResult, SourceContext


def _queries(ctx: SourceContext) -> list[str]:
    return [str(q)[:100] for q in (ctx.config.get("queries") or ctx.preferences.target_roles[:5]) if str(q).strip()]


class JoobleConnector(Connector):
    kind = "jooble"
    api_hosts = frozenset({"jooble.org"})

    def configured(self, ctx: SourceContext) -> str | None:
        return None if ctx.credentials.get("api_key") else "add your Jooble API key in Integrations"

    async def fetch(self, ctx: SourceContext) -> FetchResult:
        key = str(ctx.credentials.get("api_key") or "")
        if not re.fullmatch(r"[A-Za-z0-9-]{10,80}", key):
            raise ConnectorAuthError("jooble: add a valid API key in Integrations")
        result = FetchResult()
        locations = ctx.config.get("locations") or ["India"]
        # A free key comes with a fixed allowance (500 requests): each run spends at most this many, one per
        # search and place. Searching "India" and letting your city preferences filter keeps it to one per role.
        budget = max(1, min(int(ctx.config.get("max_requests_per_run") or 3), 30))
        searches = [(q, loc) for q in _queries(ctx) for loc in locations[:6]][:budget]
        for query, location in searches:
            try:
                response = await ctx.fetcher.post_json(f"https://jooble.org/api/{key}",
                                                       {"keywords": query, "location": str(location)[:80], "page": "1"})
            except FetchError as exc:
                raise ConnectorError(f"jooble: {exc}", retryable=exc.retryable) from exc
            if response.status_code in (401, 403):
                raise ConnectorAuthError("jooble: the API rejected the key")
            if response.status_code >= 400:
                result.warnings.append(f"jooble: HTTP {response.status_code} for '{query}' in {location}")
                continue
            for item in response.json().get("jobs", []):
                result.jobs.append(RawJob(
                    external_id=str(item.get("id") or item.get("link")),
                    url=item.get("link") or "",
                    title=re.sub(r"<[^>]+>", "", item.get("title") or ""),
                    company=item.get("company") or "",
                    description=item.get("snippet") or "",
                    location=item.get("location"),
                    employment_type=item.get("type") or None,
                    posted_at=_date(item.get("updated")),
                    apply_url=item.get("link"),
                    extra={"truncated_description": "true", "via": f"Jooble ({item.get('source') or 'aggregated'})"},
                ))
        return result


class TheMuseConnector(Connector):
    kind = "themuse"
    api_hosts = frozenset({"www.themuse.com"})

    async def fetch(self, ctx: SourceContext) -> FetchResult:
        result = FetchResult()
        params: dict[str, object] = {"page": 0}
        categories = ctx.config.get("categories") or ["Software Engineering", "Data and Analytics"]
        locations = ctx.config.get("locations") or ["Flexible / Remote", "Bengaluru, India", "Mumbai, India", "Pune, India"]
        for page in range(int(ctx.config.get("pages", 3))):
            query = {**params, "page": page, "category": categories, "location": locations}
            if ctx.credentials.get("api_key"):
                query["api_key"] = ctx.credentials["api_key"]
            try:
                response = await ctx.fetcher.get("https://www.themuse.com/api/public/jobs", params=query)
            except FetchError as exc:
                raise ConnectorError(f"the muse: {exc}", retryable=exc.retryable) from exc
            if response.status_code >= 400:
                result.warnings.append(f"the muse: HTTP {response.status_code}")
                break
            items = response.json().get("results", [])
            for item in items:
                posted = _date(item.get("publication_date"))
                result.jobs.append(RawJob(
                    external_id=str(item.get("id")),
                    url=(item.get("refs") or {}).get("landing_page") or "",
                    title=item.get("name") or "",
                    company=(item.get("company") or {}).get("name") or "",
                    description=item.get("contents") or "",
                    location="; ".join(loc.get("name", "") for loc in item.get("locations") or []) or None,
                    work_mode="remote" if any("remote" in (loc.get("name") or "").lower()
                                              for loc in item.get("locations") or []) else None,
                    posted_at=posted,
                    apply_url=(item.get("refs") or {}).get("landing_page"),
                    extra={"via": "The Muse"},
                ))
            if not items:  # the recency window itself is applied at ingest
                break
        return result

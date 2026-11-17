"""Keyword search through Adzuna's official API, and company career pages via schema.org JSON-LD.

* Adzuna (``api.adzuna.com``) covers India and other countries. It needs a free app id/key, and
  its descriptions are truncated snippets, so matching confidence is lower and applications go
  through the employer's page manually.
* Career pages: many company career sites embed ``JobPosting`` structured data (the same data
  Google Jobs reads). Each page host must be on your allowlist, and robots.txt is honoured.
"""

from __future__ import annotations

import json
import re
from datetime import date
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from ..domain import RawJob
from ..net import BlockedURL, FetchError
from ..text import sha256_text
from .ats import _date
from .base import Connector, ConnectorAuthError, ConnectorError, FetchResult, SourceContext


class AdzunaConnector(Connector):
    kind = "adzuna"
    api_hosts = frozenset({"api.adzuna.com"})

    def configured(self, ctx: SourceContext) -> str | None:
        if not (ctx.credentials.get("app_id") and ctx.credentials.get("app_key")):
            return "add your Adzuna app id and key in Integrations"
        return None

    async def fetch(self, ctx: SourceContext) -> FetchResult:
        if reason := self.configured(ctx):
            raise ConnectorAuthError(f"adzuna: {reason}")
        country = str(ctx.config.get("country", "in")).lower()
        if not re.fullmatch(r"[a-z]{2}", country):
            raise ConnectorError("adzuna: country must be a two-letter code", retryable=False)
        queries = ctx.config.get("queries") or ctx.preferences.target_roles[:4]
        result = FetchResult()
        for query in queries:
            params = {
                "app_id": ctx.credentials["app_id"],
                "app_key": ctx.credentials["app_key"],
                "what": str(query)[:100],
                "results_per_page": int(ctx.config.get("results_per_page", 30)),
                "max_days_old": int(ctx.preferences.max_posting_age_days or ctx.config.get("max_days_old", 7)),
                "content-type": "application/json",
            }
            if where := ctx.config.get("where"):
                params["where"] = str(where)[:100]
            try:
                response = await ctx.fetcher.get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", params=params)
            except FetchError as exc:
                raise ConnectorError(f"adzuna: {exc}", retryable=exc.retryable) from exc
            if response.status_code in (401, 403):
                raise ConnectorAuthError("adzuna: the API rejected the app id/key")
            if response.status_code >= 400:
                result.warnings.append(f"adzuna: HTTP {response.status_code} for '{query}'")
                continue
            for item in response.json().get("results", []):
                result.jobs.append(RawJob(
                    external_id=str(item.get("id")),
                    url=item.get("redirect_url") or "",
                    title=item.get("title") or "",
                    company=(item.get("company") or {}).get("display_name") or "",
                    description=item.get("description") or "",
                    location=(item.get("location") or {}).get("display_name"),
                    employment_type=item.get("contract_time"),
                    posted_at=_date(item.get("created")),
                    salary_min=item.get("salary_min"),
                    salary_max=item.get("salary_max"),
                    salary_currency="INR" if country == "in" and item.get("salary_min") else None,
                    salary_period="year" if item.get("salary_min") else None,
                    apply_url=item.get("redirect_url"),
                    extra={"truncated_description": "true"},
                ))
        return result


class _JsonLdExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[str] = []
        self._in = False
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and (dict(attrs).get("type") or "").lower() == "application/ld+json":
            self._in, self._buf = True, []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in:
            self.blocks.append("".join(self._buf))
            self._in = False

    def handle_data(self, data: str) -> None:
        if self._in:
            self._buf.append(data)


def _walk(node: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(node, list):
        for x in node:
            out += _walk(x)
    elif isinstance(node, dict):
        kind = node.get("@type")
        if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
            out.append(node)
        for key in ("@graph", "itemListElement", "item"):
            if key in node:
                out += _walk(node[key])
    return out


def job_postings_from_html(html: str) -> list[dict[str, Any]]:
    parser = _JsonLdExtractor()
    parser.feed(html)
    postings: list[dict[str, Any]] = []
    for block in parser.blocks:
        try:
            postings += _walk(json.loads(block))
        except json.JSONDecodeError:
            continue
    return postings


def _location(posting: dict[str, Any]) -> str | None:
    loc = posting.get("jobLocation")
    loc = loc[0] if isinstance(loc, list) and loc else loc
    if isinstance(loc, dict):
        addr = loc.get("address") or {}
        if isinstance(addr, dict):
            parts = [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]
            return ", ".join(str(p if not isinstance(p, dict) else p.get("name", "")) for p in parts if p) or None
    return None


def raw_from_jsonld(posting: dict[str, Any], page_url: str) -> RawJob | None:
    title = str(posting.get("title") or "").strip()
    if not title:
        return None
    org = posting.get("hiringOrganization") or {}
    company = org.get("name") if isinstance(org, dict) else str(org)
    salary = posting.get("baseSalary") or {}
    value = salary.get("value") if isinstance(salary, dict) else None
    smin = smax = None
    period = None
    if isinstance(value, dict):
        smin, smax = value.get("minValue") or value.get("value"), value.get("maxValue") or value.get("value")
        unit = str(value.get("unitText") or "YEAR").upper()
        period = "month" if unit == "MONTH" else "hour" if unit == "HOUR" else "year"
    ident = posting.get("identifier")
    ident = ident.get("value") if isinstance(ident, dict) else ident
    url = str(posting.get("url") or page_url)
    valid = _date(posting.get("validThrough"))
    return RawJob(
        external_id=str(ident or sha256_text(url + title)[:24]),
        url=url,
        title=title,
        company=str(company or ""),
        description=str(posting.get("description") or ""),
        location=_location(posting),
        work_mode="remote" if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE" else None,
        employment_type=str(posting.get("employmentType") or "") or None,
        posted_at=_date(posting.get("datePosted")),
        deadline=valid,
        salary_min=float(smin) if isinstance(smin, (int, float)) else None,
        salary_max=float(smax) if isinstance(smax, (int, float)) else None,
        salary_currency=salary.get("currency") if isinstance(salary, dict) else None,
        salary_period=period if smin is not None else None,  # type: ignore[arg-type]
        apply_url=url,
        is_active=valid is None or valid >= date.today(),
    )


class CareerPageConnector(Connector):
    kind = "career_page"

    def configured(self, ctx: SourceContext) -> str | None:
        return None if ctx.config.get("pages") else "add career page URLs to watch"

    async def fetch(self, ctx: SourceContext) -> FetchResult:
        result = FetchResult()
        pages = [str(p) for p in ctx.config.get("pages") or []][:50]
        # Adding a page to the watchlist approves its host; nothing else on the web is reachable.
        fetcher = ctx.fetcher.with_hosts({h for p in pages if (h := urlsplit(p).hostname)})
        for page in pages:
            try:
                response = await fetcher.get(page, accept="text/html", respect_robots=True)
            except BlockedURL as exc:
                result.warnings.append(f"skipped {page}: {exc}")
                continue
            except FetchError as exc:
                result.warnings.append(f"{page}: {exc}")
                continue
            if response.status_code >= 400:
                result.warnings.append(f"{page}: HTTP {response.status_code}")
                continue
            if re.search(r"captcha|cf-challenge|are you a robot", response.text[:20000], re.I) and not job_postings_from_html(response.text):
                result.warnings.append(f"{page}: the site asks for a CAPTCHA; open it yourself")
                continue
            found = [r for p in job_postings_from_html(response.text) if (r := raw_from_jsonld(p, page))]
            if not found:
                result.warnings.append(f"{page}: no schema.org JobPosting data on the page")
            result.jobs.extend(found)
        return result

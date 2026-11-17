"""Public job-board APIs that applicant-tracking systems publish for exactly this purpose.

* Greenhouse Job Board API: ``boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true``
* Lever Postings API:       ``api.lever.co/v0/postings/{site}?mode=json``
* Ashby Job Board API:      ``api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true``

They are read-only, unauthenticated and documented for third-party job listings. Each company
is configured by its board token (find it in the company's careers URL), e.g.
``{"boards": [{"token": "stripe", "company": "Stripe"}]}``.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from ..domain import RawJob
from ..jobs.parser import work_mode_from_text
from ..net import MAX_BOARD_BYTES, BlockedURL, FetchError
from .base import Connector, ConnectorError, FetchResult, SourceContext


def _boards(ctx: SourceContext) -> list[dict[str, str]]:
    boards = ctx.config.get("boards") or []
    valid = []
    for b in boards:
        token = str(b.get("token", "")).strip()
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", token):
            valid.append({"token": token, "company": str(b.get("company") or token)})
    return valid


_BOARD_SUFFIX = re.compile(r"\s*(job board|careers?( site| page)?|jobs|hiring)\s*$", re.I)


def _company(published: str | None, configured: str) -> str:
    """The employer's name: board titles such as "Rubrik Job Board" or "HackerRank Careers" become
    "Rubrik" and "HackerRank"; the name you configured wins when the board gives none."""
    name = _BOARD_SUFFIX.sub("", published or "").strip()
    return name or configured


def _date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):  # epoch millis (Lever)
            return datetime.fromtimestamp(value / 1000, UTC).date()
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (ValueError, OSError):
        return None


_CITY_ALIASES = {"bengaluru": ("bangalore",), "bangalore": ("bengaluru",), "mumbai": ("bombay",), "gurugram": ("gurgaon",)}


def _location_filter(ctx: SourceContext):  # noqa: ANN202
    """Optional config ``"locations": [...]`` (cities) and ``"remote_country": "India"``.

    Keeps a job whose location names one of the cities, or says remote together with the remote
    country. Jobs with no stated location are kept and scored rather than guessed about. Big global
    boards (hundreds of jobs abroad) need this.
    """
    cities = [str(t).lower().strip() for t in ctx.config.get("locations") or [] if str(t).strip()]
    terms = cities + [a for c in cities for a in _CITY_ALIASES.get(c, ())]
    country = str(ctx.config.get("remote_country") or "").lower().strip()
    if not terms and not country:
        return lambda job: True

    def keep(job) -> bool:  # noqa: ANN001
        loc = (job.location or "").lower()
        if not loc:
            return True
        if any(t in loc for t in terms):
            return True
        return bool(country) and country in loc and ("remote" in loc or job.work_mode == "remote")

    return keep


class _BoardConnector(Connector):
    async def fetch(self, ctx: SourceContext) -> FetchResult:
        result = FetchResult()
        boards = _boards(ctx)
        keep = _location_filter(ctx)
        for board in boards:
            try:
                result.jobs.extend(j for j in await self.fetch_board(ctx, board["token"], board["company"]) if keep(j))
            except BlockedURL as exc:
                raise ConnectorError(str(exc), retryable=False) from exc
            except FetchError as exc:
                if exc.status == 404:
                    result.warnings.append(f"{self.kind}: board '{board['token']}' not found")
                elif len(boards) == 1:
                    raise ConnectorError(f"{self.kind}: {exc}", retryable=exc.retryable) from exc
                else:
                    result.warnings.append(f"{self.kind}: {board['token']}: {exc}")
        return result

    def configured(self, ctx: SourceContext) -> str | None:
        return None if _boards(ctx) else "add at least one company board token"

    async def fetch_board(self, ctx: SourceContext, token: str, company: str) -> list[RawJob]:
        raise NotImplementedError


class GreenhouseConnector(_BoardConnector):
    kind = "greenhouse"
    api_hosts = frozenset({"boards-api.greenhouse.io"})

    async def fetch_board(self, ctx: SourceContext, token: str, company: str) -> list[RawJob]:
        response = await ctx.fetcher.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"},
                                         max_bytes=MAX_BOARD_BYTES)
        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code}", status=response.status_code)
        jobs = []
        for item in response.json().get("jobs", []):
            location = (item.get("location") or {}).get("name")
            jobs.append(RawJob(
                external_id=str(item["id"]),
                url=item.get("absolute_url") or "",
                title=item.get("title") or "",
                company=_company(item.get("company_name"), company),
                description=item.get("content") or "",
                location=location,
                work_mode=work_mode_from_text(location or ""),
                posted_at=_date(item.get("first_published")),  # updated_at would make edited old jobs look new
                apply_url=item.get("absolute_url"),
                is_active=True,
            ))
        return jobs


class LeverConnector(_BoardConnector):
    kind = "lever"
    api_hosts = frozenset({"api.lever.co", "api.eu.lever.co"})

    async def fetch_board(self, ctx: SourceContext, token: str, company: str) -> list[RawJob]:
        host = "api.eu.lever.co" if ctx.config.get("region") == "eu" else "api.lever.co"
        response = await ctx.fetcher.get(f"https://{host}/v0/postings/{token}", params={"mode": "json"})
        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code}", status=response.status_code)
        jobs = []
        for item in response.json():
            cats = item.get("categories") or {}
            lists = "".join(f"<h3>{x.get('text', '')}</h3><ul>{x.get('content', '')}</ul>" for x in item.get("lists") or [])
            salary = item.get("salaryRange") or {}
            interval = str(salary.get("interval") or "")
            mode = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}.get(
                str(item.get("workplaceType") or "").lower())
            jobs.append(RawJob(
                external_id=str(item["id"]),
                url=item.get("hostedUrl") or "",
                title=item.get("text") or "",
                company=company,
                description=(item.get("description") or "") + lists + (item.get("additional") or ""),
                location=cats.get("location"),
                work_mode=mode,  # type: ignore[arg-type]
                employment_type=cats.get("commitment"),
                posted_at=_date(item.get("createdAt")),
                salary_min=salary.get("min"),
                salary_max=salary.get("max"),
                salary_currency=salary.get("currency"),
                salary_period="month" if "month" in interval else "hour" if "hour" in interval else "year" if salary else None,
                apply_url=item.get("applyUrl"),
                is_active=True,
            ))
        return jobs


class AshbyConnector(_BoardConnector):
    kind = "ashby"
    api_hosts = frozenset({"api.ashbyhq.com"})

    async def fetch_board(self, ctx: SourceContext, token: str, company: str) -> list[RawJob]:
        response = await ctx.fetcher.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}",
                                         params={"includeCompensation": "true"}, max_bytes=MAX_BOARD_BYTES)
        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code}", status=response.status_code)
        jobs = []
        for item in response.json().get("jobs", []):
            if item.get("isListed") is False:
                continue
            smin = smax = cur = None
            for comp in ((item.get("compensation") or {}).get("summaryComponents") or []):
                if comp.get("compensationType") == "Salary":
                    smin, smax, cur = comp.get("minValue"), comp.get("maxValue"), comp.get("currencyCode")
                    break
            workplace = str(item.get("workplaceType") or "").lower()
            mode = "remote" if item.get("isRemote") or workplace == "remote" else {"hybrid": "hybrid", "onsite": "onsite"}.get(workplace)
            jobs.append(RawJob(
                external_id=str(item["id"]),
                url=item.get("jobUrl") or "",
                title=item.get("title") or "",
                company=company,
                description=item.get("descriptionHtml") or item.get("descriptionPlain") or "",
                location=item.get("location"),
                work_mode=mode,  # type: ignore[arg-type]
                employment_type=item.get("employmentType"),
                posted_at=_date(item.get("publishedAt")),
                salary_min=smin,
                salary_max=smax,
                salary_currency=cur,
                salary_period="year" if smin is not None else None,
                apply_url=item.get("applyUrl"),
                is_active=True,
            ))
        return jobs


class SmartRecruitersConnector(_BoardConnector):
    """SmartRecruiters public Posting API (``api.smartrecruiters.com/v1/companies/{id}/postings``).

    The list is filtered by location and the recency window first; full descriptions are fetched
    only for the postings that remain."""

    kind = "smartrecruiters"
    api_hosts = frozenset({"api.smartrecruiters.com"})

    async def fetch_board(self, ctx: SourceContext, token: str, company: str) -> list[RawJob]:
        from datetime import timedelta

        window = ctx.preferences.max_posting_age_days
        cutoff = date.today() - timedelta(days=window) if window else None
        keep = _location_filter(ctx)
        jobs: list[RawJob] = []
        for offset in range(0, 500, 100):
            response = await ctx.fetcher.get(f"https://api.smartrecruiters.com/v1/companies/{token}/postings",
                                             params={"limit": 100, "offset": offset})
            if response.status_code >= 400:
                raise FetchError(f"HTTP {response.status_code}", status=response.status_code)
            items = response.json().get("content", [])
            for item in items:
                loc = item.get("location") or {}
                posted = _date(item.get("releasedDate"))
                mode = "remote" if loc.get("remote") else "hybrid" if loc.get("hybrid") else None
                stub = RawJob(external_id=str(item.get("id")), url="https://x", title=item.get("name") or "",
                              company=(item.get("company") or {}).get("name") or company, description="",
                              location=loc.get("fullLocation"), work_mode=mode, posted_at=posted)  # type: ignore[arg-type]
                if not keep(stub) or (cutoff and posted and posted < cutoff):
                    continue
                detail = await ctx.fetcher.get(item["ref"]) if str(item.get("ref", "")).startswith(
                    "https://api.smartrecruiters.com/") else None
                if detail is None or detail.status_code >= 400:
                    continue
                d = detail.json()
                sections = ((d.get("jobAd") or {}).get("sections") or {})
                html = "".join(f"<h3>{s.get('title', '')}</h3>{s.get('text', '')}" for key in
                               ("jobDescription", "qualifications", "additionalInformation") if (s := sections.get(key)))
                jobs.append(stub.model_copy(update={
                    "url": d.get("postingUrl") or "", "description": html,
                    "employment_type": (item.get("typeOfEmployment") or {}).get("label"),
                    "apply_url": d.get("applyUrl") or d.get("postingUrl"), "is_active": d.get("active", True),
                }))
            if len(items) < 100:
                break
        return jobs

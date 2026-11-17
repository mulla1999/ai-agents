"""Fill the import form from a job posting URL.

In order of reliability:

1. Greenhouse, Lever, Ashby and SmartRecruiters links are read through those boards' public APIs.
2. Any other page is fetched once (https, public address, robots.txt respected) and its
   schema.org ``JobPosting`` data is used, the same data search engines read.
3. Otherwise the page title, meta tags and visible text are used, and the form says what is missing.

Nothing is saved here: the result fills the form and you review it before importing. Job boards
whose terms forbid automated access (LinkedIn, Naukri, Indeed, Glassdoor and similar) are not
fetched; paste the description from those yourself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..connectors.ats import _date
from ..connectors.web import job_postings_from_html, raw_from_jsonld
from ..domain import RawJob
from ..errors import ServiceError
from ..jobs.parser import work_mode_from_text
from ..jobs.safety import scan
from ..net import BlockedURL, FetchError, SafeFetcher
from ..text import html_to_text

# Sites whose terms do not allow automated reading of postings.
NO_AUTOMATION = ("linkedin.com", "naukri.com", "indeed.com", "indeed.co.in", "glassdoor.com", "glassdoor.co.in",
                 "hirist.tech", "hirist.com", "foundit.in", "monster.com", "instahyre.com", "shine.com", "iimjobs.com")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


@dataclass
class FetchedJob:
    url: str
    source: str  # greenhouse | lever | ashby | smartrecruiters | jsonld | page
    title: str = ""
    company: str = ""
    description: str = ""
    location: str | None = None
    work_mode: str | None = None
    apply_email: str | None = None
    questions: list[str] = field(default_factory=list)
    posted_at: str | None = None
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _blocked_site(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in NO_AUTOMATION)


def _board(url: str) -> tuple[str, str, str] | None:
    """(kind, board token, posting id) for a recognised ATS posting link."""
    parts = urlsplit(url)
    host, path = (parts.hostname or "").lower(), [p for p in parts.path.split("/") if p]
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io") and len(path) >= 3 \
            and path[1] == "jobs" and path[2].isdigit():
        return "greenhouse", path[0], path[2]
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io") and (gh := parse_qs(parts.query).get("gh_jid")) and path:
        return "greenhouse", path[0], gh[0]
    if host in ("jobs.lever.co", "jobs.eu.lever.co") and len(path) >= 2:
        return ("lever-eu" if ".eu." in host else "lever"), path[0], path[1]
    if host == "jobs.ashbyhq.com" and len(path) >= 2:
        return "ashby", path[0], path[1]
    if host == "jobs.smartrecruiters.com" and len(path) >= 2 and (m := re.match(r"(\d+)", path[1])):
        return "smartrecruiters", path[0], m.group(1)
    return None


async def _json(fetcher: SafeFetcher, url: str, params: dict | None = None) -> Any:
    response = await fetcher.get(url, params=params)
    if response.status_code == 404:
        raise ServiceError("not_found", "the posting was not found; it may have closed", 404)
    if response.status_code >= 400:
        raise ServiceError("fetch_failed", f"the job board answered HTTP {response.status_code}", 502)
    return response.json()


async def _from_board(fetcher: SafeFetcher, kind: str, token: str, ident: str, url: str) -> FetchedJob:
    if kind == "greenhouse":
        f = fetcher.with_hosts({"boards-api.greenhouse.io"})
        d = await _json(f, f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{ident}", {"questions": "true"})
        questions = [q.get("label", "") for q in d.get("questions") or []
                     if q.get("label") and q.get("required") and q.get("label") not in
                     ("First Name", "Last Name", "Email", "Phone", "Resume/CV", "Cover Letter")]
        return FetchedJob(url=d.get("absolute_url") or url, source=kind, title=d.get("title") or "",
                          company=d.get("company_name") or token, description=d.get("content") or "",
                          location=(d.get("location") or {}).get("name"), questions=questions[:40],
                          posted_at=str(_date(d.get("first_published")) or "") or None)
    if kind.startswith("lever"):
        host = "api.eu.lever.co" if kind == "lever-eu" else "api.lever.co"
        d = await _json(fetcher.with_hosts({host}), f"https://{host}/v0/postings/{token}/{ident}", {"mode": "json"})
        lists = "".join(f"<h3>{x.get('text', '')}</h3><ul>{x.get('content', '')}</ul>" for x in d.get("lists") or [])
        cats = d.get("categories") or {}
        mode = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}.get(
            str(d.get("workplaceType") or "").lower())
        return FetchedJob(url=d.get("hostedUrl") or url, source="lever", title=d.get("text") or "", company=token,
                          description=(d.get("description") or "") + lists + (d.get("additional") or ""),
                          location=cats.get("location"), work_mode=mode,
                          posted_at=str(_date(d.get("createdAt")) or "") or None)
    if kind == "ashby":  # the public API lists a whole board; pick the posting from it
        board = await _json(fetcher.with_hosts({"api.ashbyhq.com"}), f"https://api.ashbyhq.com/posting-api/job-board/{token}")
        d = next((j for j in board.get("jobs", []) if str(j.get("id")) == ident), None)
        if d is None:
            raise ServiceError("not_found", "the posting is not on that Ashby board any more", 404)
        workplace = str(d.get("workplaceType") or "").lower()
        mode = "remote" if d.get("isRemote") or workplace == "remote" else {"hybrid": "hybrid", "onsite": "onsite"}.get(workplace)
        return FetchedJob(url=d.get("jobUrl") or url, source=kind, title=d.get("title") or "", company=token,
                          description=d.get("descriptionHtml") or d.get("descriptionPlain") or "",
                          location=d.get("location"), work_mode=mode, posted_at=str(_date(d.get("publishedAt")) or "") or None)
    d = await _json(fetcher.with_hosts({"api.smartrecruiters.com"}),
                    f"https://api.smartrecruiters.com/v1/companies/{token}/postings/{ident}")
    sections = (d.get("jobAd") or {}).get("sections") or {}
    loc = d.get("location") or {}
    return FetchedJob(url=d.get("postingUrl") or url, source=kind, title=d.get("name") or "",
                      company=(d.get("company") or {}).get("name") or token,
                      description="".join(f"<h3>{s.get('title', '')}</h3>{s.get('text', '')}" for key in
                                          ("companyDescription", "jobDescription", "qualifications", "additionalInformation")
                                          if (s := sections.get(key))),
                      location=loc.get("fullLocation"), work_mode="remote" if loc.get("remote") else "hybrid" if loc.get("hybrid") else None,
                      posted_at=str(_date(d.get("releasedDate")) or "") or None)


class _Meta(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "meta" and (key := (a.get("property") or a.get("name") or "").lower()) and a.get("content"):
            self.meta.setdefault(key, a["content"] or "")
        self._in_title = tag == "title"

    def handle_endtag(self, tag: str) -> None:
        self._in_title = self._in_title and tag != "title"

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def _main_html(html: str) -> str:
    """The <main> or <article> part of a page when there is one, so menus and footers stay out."""
    for tag in ("main", "article"):
        if m := re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, re.I | re.S):
            return m.group(1)
    body = re.search(r"<body\b[^>]*>(.*)</body>", html, re.I | re.S)
    return re.sub(r"<(nav|header|footer|script|style|noscript)\b.*?</\1>", " ", body.group(1) if body else html, flags=re.I | re.S)


def _from_page(html: str, url: str) -> FetchedJob:
    postings = [r for p in job_postings_from_html(html) if (r := raw_from_jsonld(p, url))]
    if postings:
        raw: RawJob = postings[0]
        return FetchedJob(url=url, source="jsonld", title=raw.title, company=raw.company, description=raw.description,
                          location=raw.location, work_mode=raw.work_mode,
                          posted_at=raw.posted_at.isoformat() if raw.posted_at else None)
    meta = _Meta()
    meta.feed(html[:500_000])
    title = (meta.meta.get("og:title") or meta.title).strip()
    company = meta.meta.get("og:site_name", "").strip()
    if not company and (m := re.search(r"\s[|\-–—@]\s([^|\-–—@]{2,60})$", title)):
        company = m.group(1).strip()  # "Backend Engineer | Acme" or "Backend Engineer - Acme"
    title = re.split(r"\s[|\-–—@]\s", title)[0].strip() if company else title
    # Kept as HTML so the safety scan below still sees text hidden with CSS.
    return FetchedJob(url=url, source="page", title=title[:300], company=company[:200], description=_main_html(html)[:300_000],
                      warnings=["No structured job data on this page: the title, company and description were "
                                "read from the page text. Check them before importing."])


async def fetch_job(fetcher: SafeFetcher, url: str) -> FetchedJob:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise ServiceError("invalid_url", "enter the https:// link of the job posting", 422)
    if _blocked_site(host):
        raise ServiceError("not_allowed", f"{host} does not allow automated reading of its postings. Open the job, "
                                          "copy the title, company and description, and paste them here.", 422)
    try:
        if board := _board(url):
            job = await _from_board(fetcher, *board, url)
        else:
            response = await fetcher.with_hosts({host}).get(url, accept="text/html", respect_robots=True)
            if response.status_code >= 400:
                raise ServiceError("fetch_failed", f"the page answered HTTP {response.status_code}", 502)
            page = response.text
            if re.search(r"captcha|cf-challenge|are you a robot", page[:20000], re.I) and not job_postings_from_html(page):
                raise ServiceError("not_allowed", "the site asks for a CAPTCHA; open it yourself and paste the description", 422)
            job = _from_page(page, url)
    except BlockedURL as exc:
        raise ServiceError("not_allowed", str(exc), 422) from exc
    except FetchError as exc:
        raise ServiceError("fetch_failed", str(exc), 502) from exc

    visible, hidden = html_to_text(job.description)
    job.description = visible[:60000]
    job.work_mode = job.work_mode or work_mode_from_text(" ".join(filter(None, [job.location, visible[:3000]]))) or None
    emails = sorted({e for e in EMAIL.findall(visible) if not e.lower().startswith(("noreply", "no-reply"))})
    job.apply_email = emails[0] if len(emails) == 1 else None
    report = scan(visible, hidden, company=job.company, emails=emails)
    if report.prompt_injection:
        job.warnings.append("The page contains hidden instructions aimed at AI tools. They will be ignored, "
                            "but treat this posting with care.")
    if report.suspicious:
        job.warnings.append("Possible scam signals: " + "; ".join(report.suspicious_reasons[:3]))
    job.missing = [name for name, value in (("title", job.title), ("company", job.company)) if not value.strip()]
    if len(job.description) < 30:
        job.missing.append("description")
    return job

"""Jobs from the alert emails LinkedIn, Naukri, Indeed and Hirist send to your own inbox.

Those sites offer no job-search API to individuals and forbid scraping. Their job alerts are mail
you already receive, so reading them is how their listings reach the agent:

* IMAP over TLS (port 993) with the user's own credentials, mailbox opened **read-only**
  (messages are fetched with BODY.PEEK: nothing is marked read, moved or deleted)
* only messages from the alert senders, received within the recency window
* each job keeps its link to the original site; the description is only the alert's snippet, so
  matching confidence is lower: open the posting (or paste its text with Import) for a full score
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import re
import ssl
from dataclasses import dataclass
from datetime import date, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from ..domain import RawJob
from ..security.hosts import UnsafeHost, ensure_public_host
from .base import Connector, ConnectorAuthError, ConnectorError, FetchResult, SourceContext

MAX_MESSAGES = 300
MAX_MESSAGE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Site:
    key: str
    label: str
    senders: tuple[str, ...]
    link: re.Pattern[str]  # group 1 = the site's job id
    canonical: str  # format with {id}


SITES = (
    Site("linkedin", "LinkedIn", ("linkedin.com",),
         re.compile(r"https?://(?:[a-z]+\.)?linkedin\.com/(?:comm/)?jobs/view/(\d{6,})", re.I),
         "https://www.linkedin.com/jobs/view/{id}/"),
    Site("naukri", "Naukri", ("naukri.com",),
         re.compile(r"https?://(?:www\.)?naukri\.com/job-listings-[\w-]*?-(\d{9,})", re.I),
         "https://www.naukri.com/job-listings-{id}"),
    Site("indeed", "Indeed", ("indeed.com", "indeed.co.in"),
         re.compile(r"https?://(?:[a-z]+\.)?indeed\.(?:com|co\.in)/(?:rc/clk|viewjob|pagead/clk|m/viewjob)\?[^\s\"'<>]*?\bjk=([0-9a-f]{12,20})", re.I),
         "https://in.indeed.com/viewjob?jk={id}"),
    Site("hirist", "Hirist", ("hirist.tech", "hirist.com"),
         re.compile(r"https?://(?:www\.)?hirist\.(?:tech|com)/j/[\w-]*?(\d{5,})", re.I),
         "https://www.hirist.tech/j/{id}"),
)


class _Anchors(HTMLParser):
    """Collects (href, anchor text) and the text that follows each anchor (company · location)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self._href: str | None = None
        self._text: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in ("style", "script"):
            self._skip += 1
        if tag == "a":
            self._href, self._text = dict(attrs).get("href") or "", []

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in ("style", "script"):
            self._skip = max(0, self._skip - 1)
        if tag == "a" and self._href is not None:
            # The separate text pieces inside the link, too: newer alerts wrap a whole card
            # (title, then "Company · Location") in one link.
            chunks = [" ".join(t.split()) for t in self._text if t.strip()]
            self.items.append({"href": self._href, "text": " ".join("".join(self._text).split()), "chunks": chunks, "after": []})
            self._href = None

    def handle_data(self, data):  # noqa: ANN001
        if self._skip:
            return
        if self._href is not None:
            self._text.append(data)
        elif self.items and data.strip() and len(self.items[-1]["after"]) < 3:
            self.items[-1]["after"].append(" ".join(data.split()))


def _site_for(sender: str) -> Site | None:
    sender = sender.lower()
    return next((s for s in SITES if any(d in sender for d in s.senders)), None)


_BADGES = {"easy apply", "promoted", "actively recruiting", "be an early applicant", "new", "viewed", "apply now",
           "top applicant", "your profile matches this job", "reposted"}
_COMPANY_LINE = re.compile(r"\S\s+[·|•]\s+\S")


def parse_alert(html: str, sender: str, received: date) -> list[RawJob]:
    """Turn one alert email into jobs. Several links to one job are merged; the longest text wins."""
    site = _site_for(sender)
    if site is None:
        return []
    parser = _Anchors()
    parser.feed(html)
    found: dict[str, dict] = {}
    for item in parser.items:
        m = site.link.search(item["href"])
        title = item["text"]
        if not m or not title or len(title) < 4 or title.lower() in ("view job", "apply", "see more jobs", "view all"):
            if m and m.group(1) in found and not found[m.group(1)].get("after"):
                found[m.group(1)]["after"] = item["after"]
            continue
        chunks = [c for c in item.get("chunks", []) if c.lower() not in _BADGES]
        if len(chunks) >= 2 and any(_COMPANY_LINE.search(c) for c in chunks[1:3]):
            # Card-style link: first piece is the title, then company · location (+ badges).
            title, after = chunks[0], chunks[1:] + item["after"]
        else:
            after = item["after"]
        current = found.get(m.group(1))
        if current is None or len(title) > len(current["title"]) or (current.get("card") is None and len(chunks) >= 2
                                                                       and title != item["text"]):
            found[m.group(1)] = {"title": title[:300], "after": after or (current or {}).get("after", []),
                                 "card": title != item["text"] or None}
    jobs = []
    for job_id, info in found.items():
        details = [d for d in info["after"] if d and d.lower() not in ("·", "|") and d.lower() not in _BADGES]
        parts = re.split(r"\s+[·|•]\s+", details[0]) if details else []
        company = parts[0] if parts else ""
        location = parts[1] if len(parts) > 1 else (details[1] if len(details) > 1 else None)
        url = site.canonical.format(id=job_id)
        jobs.append(RawJob(
            external_id=f"{site.key}-{job_id}",
            url=url,
            title=info["title"],
            company=company[:300] or f"(via {site.label})",
            description=f"{info['title']}\n{' · '.join(details)}\n\nFrom your {site.label} job alert. Open the posting for the full description.",
            location=location,
            posted_at=received,
            apply_url=url,
            extra={"truncated_description": "true", "via": f"{site.label} job alert"},
        ))
    return jobs


def _html_of(message: email.message.Message) -> str:
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_type() == "text/plain":
            text = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", errors="replace")
            return re.sub(r"(https?://\S+)", r'<a href="\1">\1</a>', text)
    return ""


def _read_mailbox(host: str, port: int, username: str, password: str, folder: str, since: date,
                  senders: list[str]) -> tuple[list[tuple[str, date, str]], list[str]]:
    warnings: list[str] = []
    out: list[tuple[str, date, str]] = []
    context = ssl.create_default_context()
    try:
        client = imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=30)
    except OSError as exc:
        raise ConnectorError(f"cannot connect to {host}: {exc.__class__.__name__}") from exc
    try:
        try:
            client.login(username, password)
        except imaplib.IMAP4.error as exc:
            raise ConnectorAuthError("the mail server rejected the sign-in; for Gmail use an App Password") from exc
        status, _ = client.select(f'"{folder}"', readonly=True)  # read-only: nothing is changed
        if status != "OK":
            raise ConnectorError(f"mailbox folder '{folder}' not found", retryable=False)
        ids: list[bytes] = []
        for sender in senders:
            status, data = client.search(None, "SINCE", since.strftime("%d-%b-%Y"), "FROM", f'"{sender}"')
            if status == "OK" and data and data[0]:
                ids.extend(data[0].split())
        for msg_id in sorted(set(ids), key=int, reverse=True)[:MAX_MESSAGES]:
            status, data = client.fetch(msg_id, "(RFC822.SIZE BODY.PEEK[])")
            if status != "OK" or not data or not isinstance(data[0], tuple):
                continue
            raw = data[0][1]
            if len(raw) > MAX_MESSAGE_BYTES:
                warnings.append("skipped an oversized alert email")
                continue
            message = email.message_from_bytes(raw)
            sender = str(make_header(decode_header(message.get("From", ""))))
            try:
                received = parsedate_to_datetime(message.get("Date")).date()
            except (TypeError, ValueError):
                received = date.today()
            out.append((sender, received, _html_of(message)))
    finally:
        try:
            client.logout()
        except Exception:  # the connection may already be closed
            pass
    return out, warnings


class JobAlertsConnector(Connector):
    kind = "job_alerts"

    def configured(self, ctx: SourceContext) -> str | None:
        c = ctx.credentials
        return None if c.get("host") and c.get("username") and c.get("password") else "connect your mailbox (IMAP) in Integrations"

    async def fetch(self, ctx: SourceContext) -> FetchResult:
        if reason := self.configured(ctx):
            raise ConnectorAuthError(f"job alerts: {reason}")
        c = ctx.credentials
        host, port = str(c["host"]).strip().lower(), int(c.get("port") or 993)
        if port != 993:
            raise ConnectorError("job alerts: only IMAP over TLS on port 993 is supported", retryable=False)
        try:
            ensure_public_host(host, allow_private=ctx.settings.allow_private_hosts)
        except UnsafeHost as exc:
            raise ConnectorError(f"job alerts: {exc}", retryable=False) from exc
        sites = [s for s in SITES if s.key in (ctx.config.get("sites") or [s.key for s in SITES])]
        senders = [d for s in sites for d in s.senders]
        since = date.today() - timedelta(days=int(ctx.preferences.max_posting_age_days or 3))
        messages, warnings = await asyncio.to_thread(_read_mailbox, host, port, str(c["username"]), str(c["password"]),
                                                     str(c.get("folder") or "INBOX"), since, senders)
        result = FetchResult(warnings=warnings)
        for sender, received, html in messages:
            result.jobs.extend(parse_alert(html, sender, received))
        if not messages:
            result.warnings.append("no job-alert emails in the window; create alerts on LinkedIn, Naukri, Indeed or Hirist")
        return result

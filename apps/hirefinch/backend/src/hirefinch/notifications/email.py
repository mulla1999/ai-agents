"""Email delivery behind one interface.

* ``file``: writes ``.eml`` files to ``data_dir/mailbox``. Sends nothing; the default, and what
  tests and the demo use.
* ``smtp``: any SMTP server with STARTTLS (e.g. Gmail with an app password).
* ``gmail_api``: Gmail API with an OAuth refresh token (scope ``gmail.send`` only).

Every attachment is re-hashed right before sending and must match the checksum recorded when the
resume was generated, so an email can only ever carry the exact file it claims to.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import smtplib
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

import httpx

from ..text import sha256_file


class EmailError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class AttachmentMismatch(EmailError):
    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


@dataclass
class Attachment:
    path: str
    filename: str
    sha256: str


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    body: str
    message_id: str  # deterministic per logical message, so a retry is recognisable downstream
    attachments: list[Attachment] = field(default_factory=list)
    reply_to: str | None = None
    html: str | None = None  # built by email_compose.render_html from escaped text only


@dataclass
class DeliveryResult:
    provider: str
    message_id: str
    detail: str


def verify_attachments(attachments: list[Attachment]) -> None:
    for a in attachments:
        if not Path(a.path).is_file():
            raise AttachmentMismatch(f"attachment {a.filename} is missing")
        actual = sha256_file(a.path)
        if actual != a.sha256:
            raise AttachmentMismatch(f"attachment {a.filename} changed since it was generated")


def build_message(mail: OutgoingEmail, sender: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = mail.to
    msg["Subject"] = mail.subject.replace("\n", " ").strip()[:250]
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = mail.message_id
    if mail.reply_to:
        msg["Reply-To"] = mail.reply_to
    msg.set_content(mail.body)
    if mail.html:  # an escaped rendering of the same text (email_compose.render_html), never raw page HTML
        msg.add_alternative(mail.html, subtype="html")
    for a in mail.attachments:
        ctype = mimetypes.guess_type(a.filename)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(Path(a.path).read_bytes(), maintype=maintype, subtype=subtype, filename=a.filename)
    return msg


def message_id_for(key: str, domain: str = "hirefinch.local") -> str:
    safe = "".join(c if c.isalnum() or c in "-._" else "-" for c in key)[:120]
    return f"<{safe}@{domain}>"


class EmailSender(ABC):
    name: str
    delivers: bool  # False for the file mailbox: nothing leaves the machine
    configured: bool = True  # False when the user has not set up email: messages wait instead of failing

    @abstractmethod
    async def _send(self, msg: EmailMessage, mail: OutgoingEmail) -> str: ...

    def __init__(self, sender: str) -> None:
        self.sender = sender

    async def send(self, mail: OutgoingEmail) -> DeliveryResult:
        verify_attachments(mail.attachments)
        msg = build_message(mail, self.sender)
        detail = await self._send(msg, mail)
        return DeliveryResult(self.name, mail.message_id, detail)


class FileMailbox(EmailSender):
    name = "file"
    delivers = False

    def __init__(self, sender: str, folder: Path) -> None:
        super().__init__(sender)
        self.folder = folder

    async def _send(self, msg: EmailMessage, mail: OutgoingEmail) -> str:
        self.folder.mkdir(parents=True, exist_ok=True)
        name = mail.message_id.strip("<>").split("@")[0] + ".eml"
        path = self.folder / name
        path.write_bytes(bytes(msg))
        return f"written to local mailbox {path.name} (not sent)"


class UnconfiguredSender(EmailSender):
    """Stands in until the user (or the superadmin, for system mail) sets up email."""

    name = "unconfigured"
    delivers = False
    configured = False

    def __init__(self, reason: str) -> None:
        super().__init__("unconfigured@localhost")
        self.reason = reason

    async def _send(self, msg: EmailMessage, mail: OutgoingEmail) -> str:
        raise EmailError(self.reason, retryable=False)


class SmtpSender(EmailSender):
    name = "smtp"
    delivers = True

    def __init__(self, sender: str, host: str, port: int, username: str | None, password: str | None,
                 starttls: bool, timeout: float = 30) -> None:
        super().__init__(sender)
        self.host, self.port, self.username, self.password = host, port, username, password
        self.starttls, self.timeout = starttls, timeout

    def _blocking_send(self, msg: EmailMessage) -> str:
        context = ssl.create_default_context()
        try:
            if self.port == 465:
                server: smtplib.SMTP = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            with server:
                if self.starttls and self.port != 465:
                    server.starttls(context=context)
                if self.username and self.password:
                    server.login(self.username, self.password)
                refused = server.send_message(msg)
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailError("SMTP login failed; check the username and app password", retryable=False) from exc
        except smtplib.SMTPRecipientsRefused as exc:
            raise EmailError("the mail server refused the recipient", retryable=False) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailError(f"SMTP error: {exc.__class__.__name__}") from exc
        if refused:
            raise EmailError("the mail server refused the recipient", retryable=False)
        return f"accepted by {self.host}"

    async def _send(self, msg: EmailMessage, mail: OutgoingEmail) -> str:
        return await asyncio.to_thread(self._blocking_send, msg)


class GmailApiSender(EmailSender):
    name = "gmail_api"
    delivers = True
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

    def __init__(self, sender: str, http: httpx.AsyncClient, client_id: str, client_secret: str, refresh_token: str) -> None:
        super().__init__(sender)
        self.http, self.client_id, self.client_secret, self.refresh_token = http, client_id, client_secret, refresh_token

    async def _token(self) -> str:
        response = await self.http.post(self.TOKEN_URL, data={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "refresh_token": self.refresh_token, "grant_type": "refresh_token",
        })
        if response.status_code in (400, 401):
            raise EmailError("Gmail authorisation expired or was revoked; create a new refresh token", retryable=False)
        if response.status_code >= 400:
            raise EmailError(f"Gmail token endpoint returned HTTP {response.status_code}")
        return response.json()["access_token"]

    async def _send(self, msg: EmailMessage, mail: OutgoingEmail) -> str:
        token = await self._token()
        raw = base64.urlsafe_b64encode(bytes(msg)).decode()
        try:
            response = await self.http.post(self.SEND_URL, json={"raw": raw}, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            raise EmailError(f"Gmail API network error: {exc.__class__.__name__}") from exc
        if response.status_code in (401, 403):
            raise EmailError("Gmail API refused the request; check the gmail.send scope", retryable=False)
        if response.status_code >= 400:
            raise EmailError(f"Gmail API returned HTTP {response.status_code}", retryable=response.status_code >= 500)
        return f"accepted by Gmail (id {response.json().get('id', '?')})"


class ResendSender(EmailSender):
    """Resend's HTTPS API (resend.com): a transactional service with high daily volume, suited to
    the platform's system email. The Message-ID doubles as the idempotency key, so a retry after a
    timeout cannot send twice."""

    name = "resend"
    delivers = True
    URL = "https://api.resend.com/emails"

    def __init__(self, sender: str, http: httpx.AsyncClient, api_key: str) -> None:
        super().__init__(sender)
        self.http, self.api_key = http, api_key

    async def _send(self, msg: EmailMessage, mail: OutgoingEmail) -> str:
        body = {"from": self.sender, "to": [mail.to], "subject": msg["Subject"], "text": mail.body,
                **({"html": mail.html} if mail.html else {}),
                "headers": {"Message-ID": mail.message_id},
                "attachments": [{"filename": a.filename, "content": base64.b64encode(Path(a.path).read_bytes()).decode()}
                                for a in mail.attachments]}
        if mail.reply_to:
            body["reply_to"] = mail.reply_to
        try:
            response = await self.http.post(self.URL, json=body, timeout=30, headers={
                "Authorization": f"Bearer {self.api_key}", "Idempotency-Key": mail.message_id.strip("<>")[:256]})
        except httpx.HTTPError as exc:
            raise EmailError(f"Resend network error: {exc.__class__.__name__}") from exc
        if response.status_code in (401, 403):
            raise EmailError("Resend rejected the API key or the sending domain", retryable=False)
        if response.status_code == 422:
            raise EmailError(f"Resend refused the message: {response.json().get('message', '')[:200]}", retryable=False)
        if response.status_code >= 400:
            raise EmailError(f"Resend returned HTTP {response.status_code}", retryable=response.status_code >= 500)
        return f"accepted by Resend (id {response.json().get('id', '?')})"


__all__ = ["Attachment", "AttachmentMismatch", "DeliveryResult", "EmailError", "EmailSender", "FileMailbox",
           "GmailApiSender", "OutgoingEmail", "ResendSender", "SmtpSender", "UnconfiguredSender", "make_msgid", "message_id_for",
           "verify_attachments"]

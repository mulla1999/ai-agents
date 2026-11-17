"""Submission routes: the ways an application can actually reach an employer.

* ``email``: the posting asks for applications by email. Sends your tailored resume to that
  address. Acceptance by your mail server is recorded as *uncertain*, because no employer has
  confirmed anything yet. Needs a real email provider (SMTP or Gmail API).
* ``manual``: everything else (ATS forms, job boards). The agent prepares the package; you
  submit on the employer's site and confirm here. Form-filling automation on third-party sites is
  deliberately not implemented: those forms carry CAPTCHAs, logins and terms that forbid it.
* ``mock``: a simulated ATS for demos and tests. It keeps its own record on disk so it can be
  asked, after a crash or timeout, whether a submission actually arrived.
"""

from __future__ import annotations

import json
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ..db import Outcome
from ..notifications.email import Attachment, EmailError, EmailSender, OutgoingEmail, message_id_for


class RouteError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class SubmissionTimeout(RuntimeError):
    """The request may or may not have reached the employer. Verify before retrying."""


class NeedsPerson(RuntimeError):
    """A CAPTCHA, login or other step only you may complete."""


@dataclass
class Package:
    idempotency_key: str
    job_title: str
    company: str
    job_url: str
    apply_email: str | None
    applicant_name: str
    applicant_email: str | None
    cover_note: str
    resume: Attachment
    answers: dict[str, str] = field(default_factory=dict)
    behavior: str | None = None  # mock only


@dataclass
class Submission:
    outcome: Outcome
    reference: str | None
    evidence: dict


class Route(ABC):
    name: str

    def ready(self) -> str | None:
        """None if usable now, else the reason it is not."""
        return None

    @abstractmethod
    async def submit(self, package: Package) -> Submission: ...

    async def verify(self, idempotency_key: str) -> Submission | None:
        """Ask the other side whether a submission with this key exists. None = cannot tell."""
        return None


class ManualRoute(Route):
    name = "manual"

    async def submit(self, package: Package) -> Submission:
        raise NeedsPerson("apply on the employer's site, then confirm the application here")


class EmailRoute(Route):
    name = "email"

    def __init__(self, sender: EmailSender) -> None:
        self.sender = sender

    def ready(self) -> str | None:
        if not self.sender.delivers:
            return "email applications need a real email provider (SMTP or Gmail API); the local mailbox sends nothing"
        return None

    async def submit(self, package: Package) -> Submission:
        if not package.apply_email:
            raise RouteError("the posting has no application email address", retryable=False)
        mail = OutgoingEmail(
            to=package.apply_email,
            subject=f"Application: {package.job_title} — {package.applicant_name}",
            body=package.cover_note,
            message_id=message_id_for(package.idempotency_key),
            attachments=[package.resume],
            reply_to=package.applicant_email,
        )
        try:
            result = await self.sender.send(mail)
        except EmailError as exc:
            raise RouteError(str(exc), retryable=exc.retryable) from exc
        return Submission(Outcome.UNCERTAIN, result.message_id,
                          {"channel": "email", "to": package.apply_email, "provider": result.provider,
                           "detail": result.detail, "note": "accepted for delivery; the employer has not confirmed"})


class MockATS(Route):
    name = "mock"

    def __init__(self, store: Path) -> None:
        self.store = store

    def _load(self) -> dict:
        return json.loads(self.store.read_text()) if self.store.exists() else {}

    def _save(self, data: dict) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(json.dumps(data, indent=2))

    async def submit(self, package: Package) -> Submission:
        data = self._load()
        if package.idempotency_key in data:  # the ATS deduplicates by key, like a real idempotent API
            ref = data[package.idempotency_key]["reference"]
            return Submission(Outcome.CONFIRMED, ref, {"channel": "mock", "deduplicated": True})
        if package.behavior == "captcha":
            raise NeedsPerson("the application form requires a CAPTCHA")
        if package.behavior == "fail":
            raise RouteError("mock ATS rejected the application (HTTP 422)", retryable=False)
        if package.behavior == "flaky" and not data.get(f"flaky:{package.idempotency_key}"):
            data[f"flaky:{package.idempotency_key}"] = True
            self._save(data)
            raise RouteError("mock ATS unavailable (HTTP 503)", retryable=True)
        reference = "MOCK-" + secrets.token_hex(4).upper()
        data[package.idempotency_key] = {"reference": reference, "resume_sha256": package.resume.sha256,
                                         "company": package.company, "title": package.job_title}
        self._save(data)
        if package.behavior == "timeout":
            raise SubmissionTimeout("mock ATS did not answer in time")  # it did receive it, though
        return Submission(Outcome.CONFIRMED, reference, {"channel": "mock", "confirmation_page": f"Application {reference} received"})

    async def verify(self, idempotency_key: str) -> Submission | None:
        entry = self._load().get(idempotency_key)
        if entry is None:
            return Submission(Outcome.FAILED, None, {"channel": "mock", "verified": "not received"})
        return Submission(Outcome.CONFIRMED, entry["reference"], {"channel": "mock", "verified": "received"})

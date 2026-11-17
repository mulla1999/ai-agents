"""Browser extension: fills an employer's application form from a prepared application.

* Keys are made under Account (cookie session, CSRF-protected). A key is shown once and stored only
  as a SHA-256 hash. It expires after 90 days and can be revoked.
* ``/api/extension/*`` accepts only ``Authorization: Bearer <key>``, never the session cookie, so
  CSRF does not apply there. A key can only list your ready applications, read what is needed to
  fill a form (profile fields, prepared answers, the tailored resume) and record that you applied.
* By default the extension never submits: you review the form and click Submit. With **Auto-apply**
  (started by you from the Application Queue, which issues a short-lived signed ticket for one
  application) it submits only when every required field is filled, the resume is attached and no
  CAPTCHA is showing, after a 5-second countdown you can cancel. It is recorded as confirmed only when
  the employer's confirmation page appears. It never touches a CAPTCHA, and it refuses LinkedIn,
  Naukri and other boards that forbid automation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import ApiToken, Application, AppUser, JobPosting, JobStatus, ResumeVersion, UserStatus, aware, utcnow
from ..domain import plausible_lpa
from ..errors import ServiceError
from ..services import applications as app_service
from ..services.audit import record
from ..services.job_fetch import _blocked_site
from ..services.jobs import load_candidate
from ..services.settings_store import get_profile
from ..text import resume_filename
from .deps import DB, RT, CurrentUser, iso

router = APIRouter(tags=["extension"])
TOKEN_DAYS = 90
MAX_TOKENS = 5
MAX_RESUME_BYTES = 5 * 1024 * 1024
READY = (JobStatus.AWAITING_APPROVAL, JobStatus.READY_TO_APPLY, JobStatus.NEEDS_MANUAL)
# Questions never answered for you. Gender, ethnicity, disability, veteran status, declarations and
# similar are answered only from what you set in Profile (sent as fields below), never inferred.
SENSITIVE = ("sexual", "religio", "caste", "marital", "signature")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _token_out(t: ApiToken) -> dict[str, Any]:
    return {"id": t.id, "name": t.name, "prefix": t.prefix, "created_at": iso(t.created_at), "expires_at": iso(t.expires_at),
            "last_used_at": iso(t.last_used_at), "revoked": t.revoked_at is not None}


# ---------------------------------------------------------------- managing keys (signed-in app)


class TokenBody(BaseModel):
    name: str = Field(default="Browser extension", min_length=1, max_length=60)


@router.get("/api/account/extension-tokens")
async def list_tokens(db: DB, user: CurrentUser) -> list[dict]:
    rows = (await db.scalars(select(ApiToken).where(ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None))
                             .order_by(ApiToken.id.desc()))).all()
    return [_token_out(t) for t in rows if aware(t.expires_at) > utcnow()]


@router.post("/api/account/extension-tokens", status_code=201)
async def create_token(body: TokenBody, db: DB, user: CurrentUser) -> dict:
    active = [t for t in await list_tokens(db, user)]
    if len(active) >= MAX_TOKENS:
        raise ServiceError("limit", f"at most {MAX_TOKENS} extension keys; revoke one first", 422)
    token = "jae_" + secrets.token_urlsafe(32)
    row = ApiToken(user_id=user.id, name=" ".join(body.name.split()), token_hash=_hash(token), prefix=token[:10],
                   expires_at=utcnow() + timedelta(days=TOKEN_DAYS))
    db.add(row)
    await record(db, user.id, "account.extension_key", f"extension key '{row.name}' created", actor="user")
    await db.commit()
    return {**_token_out(row), "token": token}  # the only time the key is returned


@router.delete("/api/account/extension-tokens/{token_id}")
async def revoke_token(token_id: int, db: DB, user: CurrentUser) -> dict:
    row = await db.get(ApiToken, token_id)
    if row is None or row.user_id != user.id:
        raise ServiceError("not_found", "key not found", 404)
    row.revoked_at = utcnow()
    await record(db, user.id, "account.extension_key", f"extension key '{row.name}' revoked", actor="user")
    await db.commit()
    return {"revoked": True}


# ---------------------------------------------------------------- the extension's own API (bearer key)


async def extension_user(request: Request, db: DB) -> AppUser:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise ServiceError("unauthenticated", "add your extension key in the extension's settings", 401)
    row = await db.scalar(select(ApiToken).where(ApiToken.token_hash == _hash(header[7:].strip())))
    if row is None or row.revoked_at is not None or aware(row.expires_at) <= utcnow():
        raise ServiceError("unauthenticated", "this extension key is invalid, revoked or expired; create a new one", 401)
    if not await request.app.state.runtime.limiter.hit(f"extension:{row.id}", 300, 3600):
        raise ServiceError("rate_limited", "too many requests from the extension; try again later", 429)
    user = await db.get(AppUser, row.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise ServiceError("unauthenticated", "account not active", 401)
    row.last_used_at = utcnow()
    await db.commit()
    return user


ExtUser = Annotated[AppUser, Depends(extension_user)]


def _path(url: str | None) -> tuple[str, str]:
    parts = urlsplit(url or "")
    return (parts.hostname or "").lower().removeprefix("www."), parts.path.rstrip("/").lower()


def _matches(page: str, job: JobPosting) -> bool:
    """The page belongs to this job: same host, and one path contains the other (Lever adds /apply,
    Ashby /application, Greenhouse an #app anchor)."""
    host, path = _path(page)
    for candidate in (job.apply_url, job.url):
        h, p = _path(candidate)
        if h and h == host and p and (path.startswith(p) or (len(path) > 1 and p.startswith(path))):
            return True
    return False


async def _owned_app(db, user: AppUser, app_id: int) -> Application:  # noqa: ANN001
    app = await db.get(Application, app_id)
    if app is None or app.user_id != user.id:
        raise ServiceError("not_found", "application not found", 404)
    if app.route != "manual" or app.job.status not in READY:
        raise ServiceError("bad_state", "this application is not waiting to be filled in on the employer's site", 409)
    return app


@router.get("/api/extension/me")
async def me(user: ExtUser) -> dict:
    return {"email": user.email, "name": user.full_name}


@router.get("/api/extension/applications")
async def ready_applications(db: DB, user: ExtUser, url: str | None = Query(None, max_length=2000)) -> dict:
    if url and _blocked_site(_path(url)[0]):
        return {"blocked": True, "message": "This site does not allow automated form filling. Apply there yourself.",
                "items": []}
    apps = (await db.scalars(select(Application).join(JobPosting).where(
        Application.user_id == user.id, Application.route == "manual", JobPosting.status.in_(READY))
        .order_by(Application.updated_at.desc()).limit(50))).all()
    items = [{"id": a.id, "job_id": a.job_id, "title": a.job.title, "company": a.job.company, "status": a.job.status,
              "apply_url": a.job.apply_url or a.job.url, "matches_page": bool(url) and _matches(url, a.job)} for a in apps]
    items.sort(key=lambda i: not i["matches_page"])
    return {"blocked": False, "items": items}


@router.get("/api/extension/applications/{app_id}/autofill")
async def autofill(app_id: int, db: DB, user: ExtUser, url: str | None = Query(None, max_length=2000)) -> dict:
    if url and _blocked_site(_path(url)[0]):
        raise ServiceError("not_allowed", "this site does not allow automated form filling", 422)
    app = await _owned_app(db, user, app_id)
    profile = await get_profile(db, user.id)
    version = await db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    contact = (version.content or {}).get("contact", {}) if version else {}
    experience = (version.content or {}).get("experience", []) if version else []
    name = profile.full_name or contact.get("name") or user.full_name or ""
    first, _, last = name.strip().partition(" ")
    links = contact.get("links") or []
    resume = None
    if version is not None:
        path = Path(version.pdf_path)
        if path.is_file() and path.stat().st_size <= MAX_RESUME_BYTES:
            resume = {"filename": resume_filename(name, ".pdf"), "content_type": "application/pdf",
                      "base64": base64.b64encode(path.read_bytes()).decode()}
    fields = {
        "full_name": name, "first_name": first, "last_name": last.strip(),
        "email": str(profile.contact_email or contact.get("email") or user.email),
        "phone": profile.phone or contact.get("phone"), "location": profile.location or contact.get("location"),
        "linkedin": profile.linkedin_url or next((link for link in links if "linkedin" in link.lower()), None),
        "github": next((link for link in links if "github" in link.lower()), None),
        "portfolio": profile.portfolio_url,
        "current_company": experience[0].get("company") if experience else None,
        "current_title": experience[0].get("title") if experience else None,
        "years_experience": (f"{loaded[0].years_experience:g}" if (loaded := await load_candidate(db, user.id)) else None),
        "notice_period_days": profile.notice_period_days,
        "current_ctc_lpa": plausible_lpa(profile.current_ctc_lpa),
        "expected_ctc_lpa": plausible_lpa(profile.expected_ctc_lpa),
        "authorized_to_work_in": profile.authorized_to_work_in,
        "requires_sponsorship": profile.requires_sponsorship, "willing_to_relocate": profile.willing_to_relocate,
        # Only what you wrote in Profile: nothing here is inferred from your name or resume.
        "self_id": {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in profile.self_identification.model_dump().items() if v not in (None, "")},
        "country_of_residence": profile.common_answers.country_of_residence,
        "highest_education": profile.common_answers.highest_education or (
            ((version.content or {}).get("education") or [None])[0] if version else None),
        "managed_team": profile.common_answers.managed_team,
        "willing_onsite": profile.common_answers.willing_onsite,
        "background_check_consent": profile.common_answers.background_check_consent,
        "criminal_record": profile.common_answers.criminal_record,
        "how_did_you_hear": profile.common_answers.how_did_you_hear,
        "accept_declarations": profile.common_answers.accept_declarations,
        "employers": [e.get("company") for e in experience if e.get("company")],
        "job_company": app.job.company,
    }
    answers = [{"question": a.question, "answer": a.answer} for a in app.answers
               if a.answer and not a.needs_user and not any(w in a.question.lower() for w in SENSITIVE)]
    await record(db, user.id, "extension.autofill", f"form data for application {app.id} sent to the extension",
                 actor="user", entity=("application", app.id))
    await db.commit()
    return {"application_id": app.id, "job": {"title": app.job.title, "company": app.job.company,
                                              "apply_url": app.job.apply_url or app.job.url},
            "fields": {k: v for k, v in fields.items() if v not in (None, "", [], {})}, "answers": answers,
            "custom": {k: v for k, v in profile.custom_answers.items() if not any(w in k.lower() for w in SENSITIVE)},
            "resume": resume, "never_fill": list(SENSITIVE)}


class AppliedBody(BaseModel):
    reference: str | None = Field(default=None, max_length=300)
    # Text of the employer's "thank you / application received" page, when the extension saw it.
    confirmation_page: str | None = Field(default=None, max_length=300)
    automatic: bool = False


@router.post("/api/extension/applications/{app_id}/applied")
async def applied(app_id: int, body: AppliedBody, db: DB, rt: RT, user: ExtUser) -> dict:
    app = await _owned_app(db, user, app_id)
    urt = await rt.for_user(db, user.id)
    await app_service.confirm_manual(
        db, urt, app, (body.reference or "").strip() or None,
        "submitted automatically by the browser extension" if body.automatic else "submitted with the browser extension",
        confirmation_page=(body.confirmation_page or "").strip() or None,
        channel="extension_auto" if body.automatic else "extension")
    await db.commit()
    return {"status": app.job.status, "outcome": app.outcome}


# ---------------------------------------------------------------- Auto-apply tickets

TICKET_MINUTES = 15


def _ticket_sig(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), b"auto-apply:" + payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_ticket(secret: str, user_id: int, app_id: int) -> str:
    payload = f"{user_id}.{app_id}.{int(time.time()) + TICKET_MINUTES * 60}"
    return f"{payload}.{_ticket_sig(secret, payload)}"


def read_ticket(secret: str, ticket: str, user_id: int) -> int:
    """The application id in a valid, unexpired ticket issued to this user."""
    try:
        uid, aid, exp, sig = ticket.split(".")
        payload = f"{uid}.{aid}.{exp}"
        ok = hmac.compare_digest(sig, _ticket_sig(secret, payload)) and int(uid) == user_id and int(exp) >= time.time()
    except ValueError:
        ok = False
    if not ok:
        raise ServiceError("bad_ticket", "this Auto-apply link is invalid or expired; start it again from HireFinch", 403)
    return int(aid)


@router.post("/api/applications/{app_id}/auto-apply")
async def start_auto_apply(app_id: int, db: DB, rt: RT, user: CurrentUser) -> dict:
    """You asked for this application to be filled and submitted by the extension: returns the
    employer's form link carrying a signed, 15-minute ticket for this one application."""
    app = await _owned_app(db, user, app_id)
    from ..services.settings_store import get_policy_state

    state = await get_policy_state(db, user.id)
    if state.emergency_stop:
        raise ServiceError("emergency_stop", "emergency stop is engaged; clear it in Automation first", 423)
    url = app.job.apply_url or app.job.url
    if _blocked_site(_path(url)[0]):
        raise ServiceError("not_allowed", "this job is applied to on a site that forbids automation; apply there yourself", 422)
    ticket = make_ticket(rt.settings.secret_key.get_secret_value(), user.id, app.id)
    await record(db, user.id, "application.auto_apply", f"auto-apply started for application {app.id}", actor="user",
                 entity=("application", app.id))
    await db.commit()
    return {"url": url.split("#")[0] + "#hirefinch-apply=" + ticket, "expires_in_minutes": TICKET_MINUTES}


@router.get("/api/extension/ticket")
async def redeem_ticket(db: DB, rt: RT, user: ExtUser, t: str = Query(..., max_length=200),
                        url: str = Query(..., max_length=2000)) -> dict:
    """The extension opened a page with an Auto-apply ticket: check it, and that the page is the job's form."""
    app_id = read_ticket(rt.settings.secret_key.get_secret_value(), t, user.id)
    app = await _owned_app(db, user, app_id)
    if _blocked_site(_path(url)[0]) or not _matches(url, app.job):
        raise ServiceError("wrong_page", "this page is not the application form for that job", 422)
    data = await autofill(app_id, db, user, url)
    return {**data, "auto_submit": True}

"""Accounts API: register, verify email, sign in/out, password reset/change, account deletion.

The middleware applies double-submit CSRF to every state-changing /api request and security headers
to every response. Authentication itself is the ``CurrentUser`` dependency (``deps.py``) that every
non-public router declares; a test asserts no route is left without it.
"""

from __future__ import annotations

import hmac
import secrets
import shutil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response as StarletteResponse

from ..config import Settings
from ..db import utcnow
from ..errors import ServiceError
from ..security import google_oidc
from ..services import accounts
from ..services import integrations as integ
from ..services.integrations import system_sender
from .deps import DB, RT, SESSION_COOKIE, CurrentUser, user_out

CSRF_COOKIE = "job_agent_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

async def _rate_limit(request: Request, bucket: str, limit: int, window: int = 900) -> None:
    """Per client IP and bucket (sign-in, sign-up, reset); shared through Redis when configured."""
    key = f"{bucket}:{request.client.host if request.client else 'unknown'}"
    if not await request.app.state.runtime.limiter.hit(key, limit, window):
        raise HTTPException(429, "too many attempts; wait a few minutes and try again")


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> StarletteResponse:
        # /api/extension/* authenticates only with a bearer key, never the session cookie, so a forged
        # cross-site request carries no credentials there and needs no CSRF token.
        if (request.url.path.startswith("/api/") and request.method not in SAFE_METHODS
                and not request.url.path.startswith("/api/extension/")
                and request.url.path != "/api/client-errors"):  # write-only error log, no session used
            cookie = request.cookies.get(CSRF_COOKIE, "")
            header = request.headers.get(CSRF_HEADER, "")
            if not cookie or not hmac.compare_digest(cookie.encode(), header.encode()):
                return JSONResponse({"error": "csrf_failed", "message": "missing or invalid CSRF token"}, 403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        # SAMEORIGIN, not DENY: Resume Studio previews the PDF in a same-origin iframe.
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


router = APIRouter(prefix="/api/auth", tags=["auth"])


def _settings(request: Request) -> Settings:
    return request.app.state.settings


AppSettings = Annotated[Settings, Depends(_settings)]


def _set_session(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(SESSION_COOKIE, token, max_age=settings.login_session_hours * 3600, httponly=True,
                        secure=settings.cookie_secure, samesite="lax", path="/")


def _delivery(d: accounts.Delivery, message: str) -> dict:
    out: dict = {"message": message}
    if d.dev_link:
        out["dev_link"] = d.dev_link  # development only: no platform email configured
    return out


@router.get("/csrf")
async def csrf(response: Response, request: Request, settings: AppSettings) -> dict[str, str]:
    token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
    response.set_cookie(CSRF_COOKIE, token, httponly=False, secure=settings.cookie_secure, samesite="strict", path="/")
    return {"csrf_token": token}


@router.get("/me")
async def me(request: Request, db: DB) -> dict:
    user = await accounts.user_for_session(db, request.cookies.get(SESSION_COOKIE))
    return {"authenticated": user is not None, "user": user_out(user) if user else None}


class RegisterBody(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)
    full_name: str | None = Field(default=None, max_length=200)
    consent: bool = False


@router.post("/register", status_code=202)
async def register(body: RegisterBody, request: Request, db: DB, rt: RT, settings: AppSettings) -> dict:
    await _rate_limit(request, "register", 10)
    sender = await system_sender(db, settings, rt.http, rt.box)
    delivery = await accounts.register(db, settings, sender, email=body.email, password=body.password,
                                       full_name=body.full_name, consent=body.consent)
    await db.commit()
    if delivery.active:
        return {"message": "Your account is ready. Sign in to get started.", "active": True}
    return _delivery(delivery, "Check your email for a link to confirm your account.")


class TokenBody(BaseModel):
    token: str = Field(min_length=10, max_length=200)


@router.post("/verify-email")
async def verify_email(body: TokenBody, request: Request, db: DB) -> dict:
    await _rate_limit(request, "verify", 30)
    user = await accounts.verify_email(db, body.token)
    await db.commit()
    return {"verified": True, "email": user.email}


class EmailBody(BaseModel):
    email: str = Field(max_length=320)


@router.post("/resend-verification", status_code=202)
async def resend(body: EmailBody, request: Request, db: DB, rt: RT, settings: AppSettings) -> dict:
    await _rate_limit(request, "resend", 5)
    delivery = await accounts.resend_verification(db, settings, await system_sender(db, settings, rt.http, rt.box), body.email)
    await db.commit()
    return _delivery(delivery, "If that account is waiting for confirmation, a new link is on its way.")


class LoginBody(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response, db: DB, settings: AppSettings) -> dict:
    await _rate_limit(request, "login", 20)
    user = await accounts.authenticate(db, body.email, body.password)
    if user.totp_enabled_at is not None:
        await db.commit()
        # Password was right; no session until the second factor is checked.
        return {"authenticated": False, "two_factor_required": True,
                "challenge": accounts.two_factor_challenge(settings, user)}
    token = await accounts.create_session(db, settings, user, request.headers.get("user-agent"))
    await db.commit()
    _set_session(response, token, settings)
    return {"authenticated": True, "user": user_out(user)}


class TwoFactorBody(BaseModel):
    challenge: str = Field(max_length=500)
    code: str = Field(min_length=6, max_length=20)


@router.post("/login/2fa")
async def login_two_factor(body: TwoFactorBody, request: Request, response: Response, db: DB, rt: RT,
                           settings: AppSettings) -> dict:
    await _rate_limit(request, "login-2fa", 20)
    user = await accounts.complete_two_factor(db, settings, rt.box, body.challenge, body.code)
    token = await accounts.create_session(db, settings, user, request.headers.get("user-agent"))
    await db.commit()
    _set_session(response, token, settings)
    return {"authenticated": True, "user": user_out(user)}


@router.post("/2fa/setup")
async def two_factor_setup(user: CurrentUser, db: DB, rt: RT) -> dict:
    result = await accounts.setup_totp(db, rt.box, user)
    await db.commit()
    return result


class CodeBody(BaseModel):
    code: str = Field(min_length=6, max_length=20)


@router.post("/2fa/enable")
async def two_factor_enable(body: CodeBody, request: Request, response: Response, user: CurrentUser, db: DB, rt: RT,
                            settings: AppSettings) -> dict:
    codes = await accounts.enable_totp(db, rt.box, user, body.code)
    token = await accounts.create_session(db, settings, user, request.headers.get("user-agent"))  # this device stays in
    await db.commit()
    _set_session(response, token, settings)
    return {"enabled": True, "recovery_codes": codes}


class DisableBody(BaseModel):
    password: str = Field(max_length=256)
    code: str = Field(min_length=6, max_length=20)


@router.post("/2fa/disable")
async def two_factor_disable(body: DisableBody, request: Request, user: CurrentUser, db: DB, rt: RT) -> dict:
    await _rate_limit(request, f"2fa-disable:{user.id}", 5)  # a stolen session must not allow password guessing
    await accounts.disable_totp(db, rt.box, user, body.password, body.code)
    await db.commit()
    return {"enabled": False}


# ---------------------------------------------------------------- Sign in with Google

OAUTH_COOKIE = "job_agent_oauth"


async def _google_settings(db, rt) -> tuple[str, str] | None:  # noqa: ANN001
    row = await integ.platform_get(db, "google_oauth")
    if row is None or not row.config.get("client_id"):
        return None
    secret = rt.box.open(row.secret).get("client_secret") if row.secret else None
    return (row.config["client_id"], secret) if secret else None


def _redirect_uri(settings: Settings) -> str:
    return f"{settings.public_url.rstrip('/')}/api/auth/google/callback"


@router.get("/google/config")
async def google_config(db: DB, rt: RT) -> dict:
    return {"enabled": await _google_settings(db, rt) is not None}


@router.get("/google/start")
async def google_start(db: DB, rt: RT, settings: AppSettings) -> RedirectResponse:
    creds = await _google_settings(db, rt)
    if creds is None:
        return RedirectResponse(f"{settings.public_url.rstrip('/')}/login?error=google_unavailable", 303)
    url, state = google_oidc.start(creds[0], _redirect_uri(settings))
    response = RedirectResponse(url, 303)
    signed = URLSafeTimedSerializer(settings.secret, salt="hirefinch-oauth").dumps(state)
    # Lax, not Strict: the browser returns from Google with a top-level navigation.
    response.set_cookie(OAUTH_COOKIE, signed, max_age=600, httponly=True, secure=settings.cookie_secure,
                        samesite="lax", path="/api/auth/google")
    return response


@router.get("/google/callback")
async def google_callback(request: Request, db: DB, rt: RT, settings: AppSettings, code: str = "",
                          state: str = "", error: str = "") -> RedirectResponse:
    base = settings.public_url.rstrip("/")

    def fail(reason: str) -> RedirectResponse:
        response = RedirectResponse(f"{base}/login?error={reason}", 303)
        response.delete_cookie(OAUTH_COOKIE, path="/api/auth/google")
        return response

    await _rate_limit(request, "google", 30)
    if error or not code:
        return fail("google_cancelled")
    creds = await _google_settings(db, rt)
    try:
        saved = URLSafeTimedSerializer(settings.secret, salt="hirefinch-oauth").loads(
            request.cookies.get(OAUTH_COOKIE, ""), max_age=600)
    except (BadSignature, SignatureExpired):
        return fail("google_expired")
    if creds is None or not secrets.compare_digest(saved.get("state", ""), state):
        return fail("google_state")
    try:
        identity = await google_oidc.exchange(rt.http, code=code, client_id=creds[0], client_secret=creds[1],
                                              redirect_uri=_redirect_uri(settings), verifier=saved["verifier"],
                                              nonce=saved["nonce"])
        user = await accounts.google_account(db, settings, identity)
    except google_oidc.GoogleAuthError:
        return fail("google_failed")
    except ServiceError as exc:
        return fail(exc.code)
    if user.totp_enabled_at is not None:
        await db.commit()
        # The fragment never reaches the server or its logs; the page posts it with the code.
        response = RedirectResponse(f"{base}/login#challenge={accounts.two_factor_challenge(settings, user)}", 303)
    else:
        user.last_login_at, user.retention_warned_at = utcnow(), None
        token = await accounts.create_session(db, settings, user, request.headers.get("user-agent"))
        await db.commit()
        response = RedirectResponse(f"{base}/", 303)
        _set_session(response, token, settings)
    response.delete_cookie(OAUTH_COOKIE, path="/api/auth/google")
    return response


@router.post("/logout")
async def logout(request: Request, response: Response, db: DB, settings: AppSettings) -> dict:
    await accounts.end_session(db, request.cookies.get(SESSION_COOKIE))
    await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
    return {"authenticated": False}


@router.post("/forgot-password", status_code=202)
async def forgot(body: EmailBody, request: Request, db: DB, rt: RT, settings: AppSettings) -> dict:
    await _rate_limit(request, "reset", 5)
    delivery = await accounts.request_reset(db, settings, await system_sender(db, settings, rt.http, rt.box), body.email)
    await db.commit()
    return _delivery(delivery, "If an account exists for that email, a reset link is on its way.")


class ResetBody(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(max_length=256)


@router.post("/reset-password")
async def reset(body: ResetBody, request: Request, db: DB) -> dict:
    await _rate_limit(request, "reset-confirm", 20)
    await accounts.reset_password(db, body.token, body.password)
    await db.commit()
    return {"reset": True}


class ChangeBody(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


@router.post("/change-password")
async def change_password(body: ChangeBody, request: Request, user: CurrentUser, db: DB) -> dict:
    await _rate_limit(request, "change", 10)
    await accounts.change_password(db, user, body.current_password, body.new_password, request.cookies.get(SESSION_COOKIE))
    await db.commit()
    return {"changed": True}


class DeleteBody(BaseModel):
    password: str = Field(max_length=256)
    confirm: str = Field(max_length=50, description="type DELETE MY ACCOUNT")


@router.post("/delete-account")
async def delete_account(body: DeleteBody, request: Request, response: Response, user: CurrentUser, db: DB, rt: RT,
                         settings: AppSettings) -> dict:
    await _rate_limit(request, f"delete-account:{user.id}", 5)
    if body.confirm != "DELETE MY ACCOUNT":
        raise HTTPException(422, "type DELETE MY ACCOUNT to confirm")
    if not accounts.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "wrong password")
    user_id = user.id
    await accounts.delete_account(db, user)
    await db.commit()
    for folder in (settings.data_dir / "masters" / str(user_id), settings.artifacts_dir / "users" / str(user_id),
                   settings.data_dir / "mailbox" / str(user_id)):
        shutil.rmtree(folder, ignore_errors=True)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
    return {"deleted": True}

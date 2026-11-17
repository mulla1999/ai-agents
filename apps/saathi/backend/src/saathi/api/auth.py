"""Sign-in, sign-out and the current user."""

from __future__ import annotations

import logging
import secrets
from urllib.parse import quote

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from ..auth.deps import DB, AppSettings, CurrentUser, OptionalUser
from ..auth.google import safe_next
from ..auth.otp import consume_otp, request_otp, verify_otp
from ..auth.sessions import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    clear_session_cookie,
    create_session,
    end_session,
    set_csrf_cookie,
    set_session_cookie,
)
from ..auth.users import link_identity, sign_in_methods, upsert_google_user
from ..auth.whatsapp_login import COOKIE as WA_LOGIN_COOKIE
from ..auth.whatsapp_login import LOGIN_TTL, collect_login, start_login
from ..db import AuthIdentity, AuthProvider, Citizen, Role, User, utcnow
from ..services.access import audit
from ..services.citizens import CitizenDetails, apply_details
from ..errors import Conflict
from .schemas import AuthConfigOut, OtpRequestIn, OtpVerifyIn, RegisterIn, UserOut, WhatsAppLoginPollOut, WhatsAppLoginStartOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/config")
async def auth_config(request: Request, settings: AppSettings) -> AuthConfigOut:
    return AuthConfigOut(
        google_enabled=request.app.state.google_oauth is not None,
        whatsapp_login_enabled=settings.whatsapp_login_enabled,
    )


@router.get("/csrf")
async def csrf_token(request: Request, response: Response, settings: AppSettings) -> dict[str, str]:
    token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
    set_csrf_cookie(response, token, settings)
    return {"csrf_token": token}


@router.get("/me")
async def me(user: CurrentUser, db: DB) -> UserOut:
    return UserOut.of(user, await sign_in_methods(db, user))


@router.post("/logout", status_code=204)
async def logout(request: Request, db: DB, settings: AppSettings) -> Response:
    await end_session(db, request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response


@router.post("/otp/request", status_code=202)
async def otp_request(body: OtpRequestIn, request: Request, db: DB, settings: AppSettings) -> dict[str, str]:
    await request_otp(
        db,
        secret=settings.secret,
        sender=request.app.state.sms_sender,
        phone_raw=body.phone,
        ip=request.client.host if request.client else None,
    )
    return {"status": "sent"}


@router.post("/otp/verify")
async def otp_verify(body: OtpVerifyIn, request: Request, response: Response, db: DB, settings: AppSettings) -> UserOut:
    user = await verify_otp(db, secret=settings.secret, phone_raw=body.phone, code=body.code)
    if not user.is_active:
        await db.commit()
        raise HTTPException(status_code=403, detail="this account is disabled")
    token = await create_session(db, user, settings, request.headers.get("user-agent"))
    await db.commit()
    set_session_cookie(response, token, settings)
    return UserOut.of(user, await sign_in_methods(db, user))


@router.post("/register", status_code=201)
async def register(body: RegisterIn, request: Request, response: Response, db: DB, settings: AppSettings) -> UserOut:
    """Create an account with a verified mobile number and the person's details."""
    phone = await consume_otp(db, secret=settings.secret, phone_raw=body.phone, code=body.code)
    taken = await db.scalar(
        select(AuthIdentity.id).where(AuthIdentity.provider == AuthProvider.PHONE, AuthIdentity.subject == phone)
    ) or await db.scalar(select(User.id).where(User.phone_e164 == phone))
    if taken is not None:
        await db.commit()  # the code stays used
        raise Conflict("this mobile number already has an account; please sign in")

    user = User(phone_e164=phone, display_name=body.display_name, role=Role.CITIZEN)
    db.add(user)
    await db.flush()
    db.add(AuthIdentity(user_id=user.id, provider=AuthProvider.PHONE, subject=phone))
    citizen = Citizen(user_id=user.id, display_name=body.display_name, consent_version=settings.consent_version, consent_at=utcnow())
    apply_details(citizen, CitizenDetails.model_validate(body.model_dump(exclude={"phone", "code", "consent"})))
    db.add(citizen)
    audit(db, user, "user.register", "user", user.id)
    token = await create_session(db, user, settings, request.headers.get("user-agent"))
    await db.commit()
    set_session_cookie(response, token, settings)
    return UserOut.of(user, ["phone"])


@router.post("/link/phone")
async def link_phone(body: OtpVerifyIn, user: CurrentUser, db: DB, settings: AppSettings) -> UserOut:
    """Add a mobile number (verified by OTP) to the signed-in account."""
    phone = await consume_otp(db, secret=settings.secret, phone_raw=body.phone, code=body.code)
    try:
        await link_identity(db, user, AuthProvider.PHONE, phone)
    except Conflict:
        await db.commit()  # keep the consumed code consumed
        raise
    await db.commit()
    return UserOut.of(user, await sign_in_methods(db, user))


@router.post("/whatsapp/start")
async def whatsapp_login_start(
    request: Request, response: Response, db: DB, settings: AppSettings
) -> WhatsAppLoginStartOut:
    if not settings.whatsapp_login_enabled:
        raise HTTPException(status_code=404, detail="WhatsApp sign-in is not configured")
    code, token = await start_login(db, request.client.host if request.client else None)
    seconds = int(LOGIN_TTL.total_seconds())
    response.set_cookie(
        WA_LOGIN_COOKIE, token, max_age=seconds, httponly=True, secure=settings.cookie_secure,
        samesite="lax", path="/api/auth/whatsapp",
    )  # fmt: skip
    link = f"https://wa.me/{settings.whatsapp_login_number}?text={quote(f'LOGIN {code}')}"
    return WhatsAppLoginStartOut(code=code, link=link, expires_in_seconds=seconds)


@router.post("/whatsapp/poll")
async def whatsapp_login_poll(
    request: Request, response: Response, db: DB, settings: AppSettings
) -> WhatsAppLoginPollOut:
    user = await collect_login(db, request.cookies.get(WA_LOGIN_COOKIE))
    if user is None:
        return WhatsAppLoginPollOut(status="pending")
    if not user.is_active:
        await db.commit()
        raise HTTPException(status_code=403, detail="this account is disabled")
    token = await create_session(db, user, settings, request.headers.get("user-agent"))
    await db.commit()
    set_session_cookie(response, token, settings)
    response.delete_cookie(WA_LOGIN_COOKIE, path="/api/auth/whatsapp")
    return WhatsAppLoginPollOut(status="signed_in", user=UserOut.of(user, await sign_in_methods(db, user)))


@router.get("/google/login")
async def google_login(
    request: Request, settings: AppSettings, current: OptionalUser, next: str = "/", link: bool = False
) -> Response:
    oauth = request.app.state.google_oauth
    if oauth is None:
        raise HTTPException(status_code=404, detail="Google sign-in is not configured")
    request.session["next"] = safe_next(next)
    if link:
        if current is None:
            raise HTTPException(status_code=401, detail="sign in required")
        # Remember who asked, so the callback links Google to this account instead of signing in.
        request.session["link_user"] = str(current.id)
    return await oauth.google.authorize_redirect(request, f"{settings.public_url}/api/auth/google/callback")


@router.get("/google/callback")
async def google_callback(request: Request, db: DB, settings: AppSettings, current: OptionalUser) -> Response:
    oauth = request.app.state.google_oauth
    if oauth is None:
        raise HTTPException(status_code=404, detail="Google sign-in is not configured")
    failed = RedirectResponse(f"{settings.public_url}/login?error=google", status_code=303)
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        log.warning("Google sign-in failed: %s", exc.error)
        return failed
    claims = token.get("userinfo") or {}
    if not claims.get("sub") or not claims.get("email") or not claims.get("email_verified"):
        return failed

    link_user = request.session.pop("link_user", None)
    if link_user is not None:
        # Linking only applies if the same person is still signed in.
        if current is None or str(current.id) != link_user:
            return RedirectResponse(f"{settings.public_url}/login", status_code=303)
        try:
            await link_identity(db, current, AuthProvider.GOOGLE, claims["sub"])
        except Conflict:
            return RedirectResponse(f"{settings.public_url}/account?error=google_in_use", status_code=303)
        if current.email is None and await db.scalar(select(User.id).where(User.email == claims["email"].lower())) is None:
            current.email = claims["email"].lower()
        await db.commit()
        return RedirectResponse(f"{settings.public_url}/account?linked=google", status_code=303)

    user = await upsert_google_user(
        db,
        subject=claims["sub"],
        email=claims["email"],
        name=claims.get("name"),
        admin_emails=settings.admin_email_set,
    )
    if not user.is_active:
        await db.commit()
        return RedirectResponse(f"{settings.public_url}/login?error=disabled", status_code=303)
    session_token = await create_session(db, user, settings, request.headers.get("user-agent"))
    await db.commit()

    response = RedirectResponse(settings.public_url + safe_next(request.session.pop("next", "/")), status_code=303)
    set_session_cookie(response, session_token, settings)
    return response

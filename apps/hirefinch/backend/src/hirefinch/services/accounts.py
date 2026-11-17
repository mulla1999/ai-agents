"""Accounts: registration with email verification, sign-in, sessions, password reset, deletion.

* Responses never reveal whether an email is registered (register / forgot-password always say
  "check your email").
* Sessions and tokens are random; only their SHA-256 is stored. Tokens are single-use and expire.
* 10 failed sign-ins lock an account for 15 minutes. Changing or resetting a password ends every
  other session.
* System emails (verify, reset) go through the platform sender the superadmin configures. Outside
  production, when none is configured, the link is returned to the caller instead, for local testing.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import (
    Application,
    ApplicationAttempt,
    AppUser,
    AuthToken,
    EmailDelivery,
    EmailDraft,
    JobPosting,
    ResumeTailoringRun,
    ResumeVersion,
    Role,
    UserSession,
    UserStatus,
    aware,
    utcnow,
)
from ..errors import ServiceError
from ..notifications.email import EmailError, EmailSender, OutgoingEmail, message_id_for
from ..security.passwords import WeakPassword, check_strength, hash_password, verify_password
from .audit import record
from .integrations import platform_config
from ..config import BRAND

VERIFY_TTL = timedelta(hours=48)
RESET_TTL = timedelta(hours=1)
MAX_FAILED = 10
LOCKOUT = timedelta(minutes=15)
_TOUCH = timedelta(minutes=5)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    try:
        return validate_email(email.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise ServiceError("invalid_email", str(exc), 422) from exc


@dataclass
class Delivery:
    sent: bool
    dev_link: str | None = None  # only outside production, when no platform email is set up
    active: bool = False  # the account works straight away (the superadmin turned email confirmation off)


async def _send_system(sender: EmailSender, settings: Settings, to: str, subject: str, body: str, link: str,
                       key: str) -> Delivery:
    if not sender.configured:
        if settings.environment == "production":
            raise ServiceError("email_unavailable", "sign-ups are not ready yet: the site owner still has to finish email setup. Please try again later.", 503)
        return Delivery(False, link)
    try:
        await sender.send(OutgoingEmail(to=to, subject=subject, body=body, message_id=message_id_for(key)))
    except EmailError as exc:
        raise ServiceError("email_failed", "could not send the email right now; try again later", 502) from exc
    return Delivery(True)


async def _issue(db: AsyncSession, user: AppUser, purpose: str, ttl: timedelta) -> str:
    await db.execute(delete(AuthToken).where(AuthToken.user_id == user.id, AuthToken.purpose == purpose,
                                             AuthToken.used_at.is_(None)))
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(user_id=user.id, purpose=purpose, token_hash=_hash(token), expires_at=utcnow() + ttl))
    return token


async def _consume(db: AsyncSession, token: str, purpose: str) -> AppUser:
    row = await db.scalar(select(AuthToken).where(AuthToken.token_hash == _hash(token), AuthToken.purpose == purpose))
    if row is None or row.used_at is not None or aware(row.expires_at) <= utcnow():
        raise ServiceError("invalid_token", "this link is invalid or has expired; request a new one", 400)
    row.used_at = utcnow()
    user = await db.get(AppUser, row.user_id)
    assert user is not None
    return user


async def _verification_mail(db: AsyncSession, settings: Settings, sender: EmailSender, user: AppUser) -> Delivery:
    token = await _issue(db, user, "verify_email", VERIFY_TTL)
    link = f"{settings.public_url.rstrip('/')}/verify-email?token={token}"
    body = (f"Hello{(' ' + user.full_name) if user.full_name else ''},\n\nConfirm your email to activate your {BRAND} "
            f"account:\n{link}\n\nThe link works for 48 hours. If you did not sign up, ignore this email.")
    return await _send_system(sender, settings, user.email, f"Confirm your {BRAND} account", body, link,
                              f"verify-{user.id}-{token[:8]}")


async def register(db: AsyncSession, settings: Settings, sender: EmailSender, *, email: str, password: str,
                   full_name: str | None, consent: bool) -> Delivery:
    if not consent:
        raise ServiceError("consent_required", "accept the terms and privacy notice to create an account", 422)
    email = normalize_email(email)
    reg = await platform_config(db, "registration")
    is_superadmin = bool(settings.superadmin_email) and email == normalize_email(settings.superadmin_email or "x@x.invalid")
    if not is_superadmin:
        if not reg.get("open", True):
            raise ServiceError("registration_closed", "new sign-ups are closed", 403)
        domains = reg.get("allowed_domains") or []
        if domains and email.split("@")[1] not in domains:
            raise ServiceError("domain_not_allowed", "sign-ups are limited to specific email domains", 403)
    try:
        check_strength(password, email)
    except WeakPassword as exc:
        raise ServiceError("weak_password", str(exc), 422) from exc
    verify = reg.get("verify_email", True) or is_superadmin
    existing = await db.scalar(select(AppUser).where(AppUser.email == email))
    if existing is not None:
        # Same answer as a new sign-up: the response never reveals that the address is registered.
        if not verify:
            return Delivery(False, active=True)
        if existing.status == UserStatus.PENDING:
            return await _verification_mail(db, settings, sender, existing)
        return Delivery(sender.configured, None)
    user = AppUser(email=email, full_name=(full_name or "").strip()[:200] or None, password_hash=hash_password(password),
                   role=Role.SUPERADMIN if is_superadmin else Role.USER,
                   status=UserStatus.PENDING if verify else UserStatus.ACTIVE, consent_at=utcnow())
    db.add(user)
    await db.flush()
    await record(db, user.id, "account.registered", "account created" if verify else "account created without email confirmation",
                 actor="user")
    if not verify:
        # email_verified_at stays empty: if the real owner of the address later signs in with Google,
        # this account is reset to them (see google_account).
        return Delivery(False, active=True)
    return await _verification_mail(db, settings, sender, user)


async def verify_email(db: AsyncSession, token: str) -> AppUser:
    user = await _consume(db, token, "verify_email")
    if user.status == UserStatus.DISABLED:
        raise ServiceError("disabled", "this account is disabled", 403)
    user.status, user.email_verified_at = UserStatus.ACTIVE, utcnow()
    await record(db, user.id, "account.verified", "email verified", actor="user")
    return user


async def resend_verification(db: AsyncSession, settings: Settings, sender: EmailSender, email: str) -> Delivery:
    user = await db.scalar(select(AppUser).where(AppUser.email == normalize_email(email)))
    if user is None or user.status != UserStatus.PENDING:
        return Delivery(sender.configured, None)
    return await _verification_mail(db, settings, sender, user)


async def authenticate(db: AsyncSession, email: str, password: str) -> AppUser:
    try:
        email = normalize_email(email)
    except ServiceError:
        raise ServiceError("bad_credentials", "wrong email or password", 401) from None
    user = await db.scalar(select(AppUser).where(AppUser.email == email))
    now = utcnow()
    if user is not None and user.locked_until and aware(user.locked_until) > now:
        raise ServiceError("locked", "too many failed sign-ins; try again in 15 minutes", 429)
    if user is None or not verify_password(password, user.password_hash):
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED:
                user.locked_until, user.failed_logins = now + LOCKOUT, 0
                await record(db, user.id, "account.locked", "locked after repeated failed sign-ins", level="warning")
            await db.commit()
        raise ServiceError("bad_credentials", "wrong email or password", 401)
    if user.status == UserStatus.DISABLED:
        raise ServiceError("disabled", "this account is disabled; contact the administrator", 403)
    if user.status == UserStatus.PENDING:
        raise ServiceError("unverified", "confirm your email first: check your inbox for the link", 403)
    user.failed_logins, user.locked_until, user.last_login_at, user.retention_warned_at = 0, None, now, None
    return user


async def create_session(db: AsyncSession, settings: Settings, user: AppUser, user_agent: str | None) -> str:
    token = secrets.token_urlsafe(32)
    db.add(UserSession(user_id=user.id, token_hash=_hash(token), user_agent=(user_agent or "")[:255] or None,
                       expires_at=utcnow() + timedelta(hours=settings.login_session_hours)))
    await record(db, user.id, "account.login", "signed in", actor="user")
    return token


async def user_for_session(db: AsyncSession, token: str | None) -> AppUser | None:
    if not token:
        return None
    session = await db.scalar(select(UserSession).where(UserSession.token_hash == _hash(token)))
    if session is None:
        return None
    now = utcnow()
    if aware(session.expires_at) <= now:
        await db.delete(session)
        await db.commit()
        return None
    user = await db.get(AppUser, session.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        return None
    if now - aware(session.last_seen_at) > _TOUCH:  # type: ignore[operator]
        session.last_seen_at = now
        await db.commit()
    return user


async def end_session(db: AsyncSession, token: str | None) -> None:
    if token:
        await db.execute(delete(UserSession).where(UserSession.token_hash == _hash(token)))


async def end_all_sessions(db: AsyncSession, user_id: int, keep_token: str | None = None) -> None:
    query = delete(UserSession).where(UserSession.user_id == user_id)
    if keep_token:
        query = query.where(UserSession.token_hash != _hash(keep_token))
    await db.execute(query)


async def request_reset(db: AsyncSession, settings: Settings, sender: EmailSender, email: str) -> Delivery:
    try:
        user = await db.scalar(select(AppUser).where(AppUser.email == normalize_email(email)))
    except ServiceError:
        return Delivery(sender.configured, None)
    if user is None or user.status == UserStatus.DISABLED:
        return Delivery(sender.configured, None)  # same answer either way
    token = await _issue(db, user, "reset_password", RESET_TTL)
    link = f"{settings.public_url.rstrip('/')}/reset-password?token={token}"
    body = (f"Someone asked to reset the password for your {BRAND} account.\n\nReset it here (valid for 1 hour):\n"
            f"{link}\n\nIf this was not you, ignore this email; your password stays the same.")
    await record(db, user.id, "account.reset_requested", "password reset requested", actor="user")
    return await _send_system(sender, settings, user.email, f"Reset your {BRAND} password", body, link,
                              f"reset-{user.id}-{token[:8]}")


async def reset_password(db: AsyncSession, token: str, new_password: str) -> AppUser:
    user = await _consume(db, token, "reset_password")
    try:
        check_strength(new_password, user.email)
    except WeakPassword as exc:
        raise ServiceError("weak_password", str(exc), 422) from exc
    user.password_hash, user.failed_logins, user.locked_until = hash_password(new_password), 0, None
    if user.status == UserStatus.PENDING:  # following an emailed link proves the address
        user.status, user.email_verified_at = UserStatus.ACTIVE, utcnow()
    await end_all_sessions(db, user.id)
    await record(db, user.id, "account.password_reset", "password reset; all sessions ended", actor="user")
    return user


async def change_password(db: AsyncSession, user: AppUser, current: str, new: str, keep_token: str | None) -> None:
    if not verify_password(current, user.password_hash):
        raise ServiceError("bad_credentials", "your current password is wrong", 401)
    try:
        check_strength(new, user.email)
    except WeakPassword as exc:
        raise ServiceError("weak_password", str(exc), 422) from exc
    user.password_hash = hash_password(new)
    await end_all_sessions(db, user.id, keep_token)
    await record(db, user.id, "account.password_changed", "password changed; other sessions ended", actor="user")


async def delete_account(db: AsyncSession, user: AppUser) -> None:
    """Removes the user and every row they own. Files are removed by the caller after commit."""
    if user.role == Role.SUPERADMIN:
        raise ServiceError("forbidden", "the superadmin account cannot be deleted from the app", 403)
    # Children with RESTRICT references go first, in dependency order; the rest cascade with the user.
    mine = user.id
    app_ids = select(Application.id).where(Application.user_id == mine)
    await db.execute(delete(ApplicationAttempt).where(ApplicationAttempt.application_id.in_(app_ids)))
    await db.execute(delete(Application).where(Application.user_id == mine))
    draft_ids = select(EmailDraft.id).where(EmailDraft.user_id == mine)
    await db.execute(delete(EmailDelivery).where(EmailDelivery.draft_id.in_(draft_ids)))
    await db.execute(delete(EmailDraft).where(EmailDraft.user_id == mine))
    await db.execute(delete(ResumeTailoringRun).where(ResumeTailoringRun.user_id == mine))
    await db.execute(delete(ResumeVersion).where(ResumeVersion.user_id == mine))
    await db.execute(update(JobPosting).where(JobPosting.user_id == mine).values(duplicate_of_id=None))
    await db.execute(delete(JobPosting).where(JobPosting.user_id == mine))
    # Every other table with an owner, explicitly: correctness never depends on ON DELETE CASCADE.
    from ..db import Base

    for table in reversed(Base.metadata.sorted_tables):
        if "user_id" in table.c and table.name != "app_user":
            await db.execute(table.delete().where(table.c.user_id == mine))
    await record(db, None, "account.deleted", f"account {mine} deleted with all its data", actor="user")
    await db.delete(user)


async def ensure_superadmin_role(db: AsyncSession, settings: Settings) -> None:
    """The configured superadmin email always holds the superadmin role (it cannot be demoted)."""
    if not settings.superadmin_email:
        return
    user = await db.scalar(select(AppUser).where(AppUser.email == normalize_email(settings.superadmin_email)))
    if user is not None and user.role != Role.SUPERADMIN:
        user.role = Role.SUPERADMIN
        await record(db, user.id, "account.superadmin", "superadmin role assigned from configuration")


# ---------------------------------------------------------------- two-factor sign-in (TOTP)

CHALLENGE_TTL = 300  # seconds to enter the code after the password


def _challenges(settings: Settings):  # noqa: ANN202
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(settings.secret, salt="hirefinch-2fa")


def two_factor_challenge(settings: Settings, user: AppUser) -> str:
    return _challenges(settings).dumps({"u": user.id, "n": secrets.token_hex(8)})


async def setup_totp(db: AsyncSession, box, user: AppUser) -> dict:  # noqa: ANN001
    from ..security import totp

    if user.totp_enabled_at is not None:
        raise ServiceError("already_enabled", "two-factor sign-in is already on", 409)
    secret = totp.new_secret()
    user.totp_secret = box.seal({"secret": secret})  # pending until confirmed with a code
    uri = totp.provisioning_uri(secret, user.email)
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": totp.qr_svg(uri)}


async def enable_totp(db: AsyncSession, box, user: AppUser, code: str) -> list[str]:  # noqa: ANN001
    from ..security import totp

    secret = box.open(user.totp_secret).get("secret") if user.totp_secret else None
    if not secret or user.totp_enabled_at is not None:
        raise ServiceError("no_setup", "start two-factor setup first", 409)
    step = totp.verify(secret, code, last_step=None)
    if step is None:
        raise ServiceError("bad_code", "that code is not right; check the time on your phone and try again", 422)
    codes = totp.new_recovery_codes()
    user.totp_enabled_at, user.totp_last_step = utcnow(), step
    user.recovery_codes = [totp.hash_code(c) for c in codes]
    await end_all_sessions(db, user.id)  # sign in again with the second factor everywhere
    await record(db, user.id, "account.2fa_enabled", "two-factor sign-in turned on", actor="user")
    return codes


async def check_second_factor(db: AsyncSession, box, user: AppUser, code: str) -> bool:  # noqa: ANN001
    """A current TOTP code (each accepted once) or an unused recovery code (then spent)."""
    from ..security import totp

    secret = box.open(user.totp_secret).get("secret") if user.totp_secret else None
    if secret and (step := totp.verify(secret, code, last_step=user.totp_last_step)) is not None:
        user.totp_last_step = step
        return True
    hashed = totp.hash_code(code)
    if hashed in (user.recovery_codes or []):
        user.recovery_codes = [c for c in user.recovery_codes if c != hashed]
        await record(db, user.id, "account.recovery_code_used", f"recovery code used; {len(user.recovery_codes)} left",
                     actor="user", level="warning")
        return True
    return False


async def complete_two_factor(db: AsyncSession, settings: Settings, box, challenge: str, code: str) -> AppUser:  # noqa: ANN001
    from itsdangerous import BadSignature, SignatureExpired

    try:
        data = _challenges(settings).loads(challenge, max_age=CHALLENGE_TTL)
    except SignatureExpired:
        raise ServiceError("expired", "the sign-in took too long; enter your password again", 401) from None
    except BadSignature:
        raise ServiceError("bad_challenge", "sign in again", 401) from None
    user = await db.get(AppUser, int(data["u"]))
    if user is None or user.status != UserStatus.ACTIVE or user.totp_enabled_at is None:
        raise ServiceError("bad_challenge", "sign in again", 401)
    if user.locked_until and aware(user.locked_until) > utcnow():
        raise ServiceError("locked", "too many failed sign-ins; try again in 15 minutes", 429)
    if not await check_second_factor(db, box, user, code):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED:
            user.locked_until, user.failed_logins = utcnow() + LOCKOUT, 0
        await db.commit()
        raise ServiceError("bad_code", "that code is not right", 401)
    user.failed_logins, user.locked_until, user.last_login_at, user.retention_warned_at = 0, None, utcnow(), None
    return user


async def disable_totp(db: AsyncSession, box, user: AppUser, password: str, code: str) -> None:  # noqa: ANN001
    if user.totp_enabled_at is None:
        raise ServiceError("not_enabled", "two-factor sign-in is not on", 409)
    if not verify_password(password, user.password_hash) or not await check_second_factor(db, box, user, code):
        raise ServiceError("bad_credentials", "password or code is wrong", 401)
    user.totp_secret, user.totp_enabled_at, user.totp_last_step, user.recovery_codes = None, None, None, []
    await record(db, user.id, "account.2fa_disabled", "two-factor sign-in turned off", actor="user", level="warning")


# ---------------------------------------------------------------- Sign in with Google


async def google_account(db: AsyncSession, settings: Settings, identity) -> AppUser:  # noqa: ANN001
    """Find the account for a verified Google identity, linking or creating it as the rules allow."""
    user = await db.scalar(select(AppUser).where(AppUser.google_sub == identity.sub))
    if user is None:
        user = await db.scalar(select(AppUser).where(AppUser.email == normalize_email(identity.email)))
        if user is not None:
            if user.google_sub and user.google_sub != identity.sub:
                raise ServiceError("conflict", "this email is linked to a different Google account", 409)
            if user.email_verified_at is None:
                # Someone registered this address without ever proving it. Google has now proved who owns
                # it, so nothing the earlier registrant set may survive: password, two-factor, sessions.
                user.password_hash = None
                user.totp_secret, user.totp_enabled_at, user.totp_last_step, user.recovery_codes = None, None, None, []
                await end_all_sessions(db, user.id)
                await record(db, user.id, "account.unverified_reset", "unverified sign-up taken over by the verified owner",
                             level="warning")
            user.google_sub = identity.sub  # Google verified the address, so linking is safe
            await record(db, user.id, "account.google_linked", "Google sign-in linked", actor="user")
    if user is None:
        email = normalize_email(identity.email)
        reg = await platform_config(db, "registration")
        is_superadmin = bool(settings.superadmin_email) and email == normalize_email(settings.superadmin_email or "x@x.invalid")
        if not is_superadmin:
            if not reg.get("open", True):
                raise ServiceError("registration_closed", "new sign-ups are closed", 403)
            domains = reg.get("allowed_domains") or []
            if domains and email.split("@")[1] not in domains:
                raise ServiceError("domain_not_allowed", "sign-ups are limited to specific email domains", 403)
        user = AppUser(email=email, full_name=(identity.name or "")[:200] or None, google_sub=identity.sub,
                       role=Role.SUPERADMIN if is_superadmin else Role.USER, status=UserStatus.ACTIVE,
                       email_verified_at=utcnow(), consent_at=utcnow())
        db.add(user)
        await db.flush()
        await record(db, user.id, "account.registered", "account created with Google", actor="user")
    if user.status == UserStatus.DISABLED:
        raise ServiceError("disabled", "this account is disabled; contact the administrator", 403)
    if user.status == UserStatus.PENDING:  # Google proved the address
        user.status, user.email_verified_at = UserStatus.ACTIVE, utcnow()
    return user

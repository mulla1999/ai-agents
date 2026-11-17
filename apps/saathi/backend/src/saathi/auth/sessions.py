"""Server-side login sessions. The browser holds a random token; the database holds only its SHA-256."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import User, UserSession, utcnow

SESSION_COOKIE = "saathi_session"
CSRF_COOKIE = "saathi_csrf"
CSRF_HEADER = "x-csrf-token"
_TOUCH_INTERVAL = timedelta(minutes=5)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def aware(moment: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def create_session(db: AsyncSession, user: User, settings: Settings, user_agent: str | None) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=now + timedelta(days=settings.login_session_days),
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    user.last_login_at = now
    return token


async def user_for_token(db: AsyncSession, token: str | None) -> User | None:
    if not token:
        return None
    session = await db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if session is None:
        return None
    now = utcnow()
    if aware(session.expires_at) <= now:
        await db.delete(session)
        await db.commit()
        return None
    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    if now - aware(session.last_seen_at) > _TOUCH_INTERVAL:
        session.last_seen_at = now
        await db.commit()
    return user


async def end_session(db: AsyncSession, token: str | None) -> None:
    if token:
        await db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
        await db.commit()


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.login_session_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")


def set_csrf_cookie(response: Response, token: str, settings: Settings) -> None:
    # Readable by JavaScript on purpose: the SPA copies it into the X-CSRF-Token header.
    response.set_cookie(CSRF_COOKIE, token, httponly=False, secure=settings.cookie_secure, samesite="lax", path="/")

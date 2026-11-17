"""Sign in with WhatsApp ("reverse OTP"): free, because messages people send to the bot cost nothing.

1. The browser asks for a code; it gets the code plus an HttpOnly cookie holding a random token.
2. The person sends "LOGIN <code>" to the bot. Meta's signed webhook proves which number sent it.
3. The browser polls; once the code is confirmed, the token holder (only) gets a session.

Known limit, as with any code-based sign-in: someone who tricks a person into sending *their* code
can sign in as that person. The bot's reply warns people to ignore codes they did not request.
"""

from __future__ import annotations

import re
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import User, WhatsAppLogin, utcnow
from ..errors import BadRequest, TooManyRequests
from .sessions import aware, hash_token
from .users import upsert_phone_user

LOGIN_TTL = timedelta(minutes=5)
IP_WINDOW, IP_LIMIT = timedelta(hours=1), 10
COOKIE = "saathi_wa_login"
_LOGIN_TEXT = re.compile(r"^\s*(?:login|लॉगिन)\s*[-:]?\s*(\d{6})\s*$", re.IGNORECASE)


def login_code(text: str | None) -> str | None:
    """The code in a 'LOGIN 123456' message, or None if this is not a sign-in message."""
    match = _LOGIN_TEXT.match(text or "")
    return match.group(1) if match else None


async def start_login(db: AsyncSession, ip: str | None) -> tuple[str, str]:
    """Create a challenge. Returns (code to show, browser token for the cookie)."""
    now = utcnow()
    if ip:
        recent = await db.scalar(
            select(func.count())
            .select_from(WhatsAppLogin)
            .where(WhatsAppLogin.ip == ip, WhatsAppLogin.created_at >= now - IP_WINDOW)
        )
        if recent >= IP_LIMIT:
            raise TooManyRequests("too many sign-in attempts; please wait and try again")

    pending = set(
        (
            await db.scalars(
                select(WhatsAppLogin.code).where(
                    WhatsAppLogin.confirmed_at.is_(None), WhatsAppLogin.created_at >= now - LOGIN_TTL
                )
            )
        ).all()
    )
    code = f"{secrets.randbelow(10**6):06d}"
    while code in pending:  # codes must be unambiguous while they are live
        code = f"{secrets.randbelow(10**6):06d}"
    token = secrets.token_urlsafe(32)
    db.add(WhatsAppLogin(code=code, browser_token_hash=hash_token(token), expires_at=now + LOGIN_TTL, ip=ip))
    await db.commit()
    return code, token


async def confirm_login(db: AsyncSession, code: str, phone_e164: str) -> bool:
    """Called from the WhatsApp webhook with the sender's verified number."""
    challenge = await db.scalar(
        select(WhatsAppLogin)
        .where(WhatsAppLogin.code == code, WhatsAppLogin.confirmed_at.is_(None))
        .order_by(WhatsAppLogin.created_at.desc())
        .limit(1)
    )
    if challenge is None or aware(challenge.expires_at) <= utcnow():
        return False
    challenge.phone_e164 = phone_e164
    challenge.confirmed_at = utcnow()
    await db.commit()
    return True


async def collect_login(db: AsyncSession, token: str | None) -> User | None:
    """The signed-in user once the code is confirmed; None while still waiting."""
    challenge = await db.scalar(select(WhatsAppLogin).where(WhatsAppLogin.browser_token_hash == hash_token(token or "")))
    if challenge is None or challenge.used_at is not None or aware(challenge.expires_at) <= utcnow():
        raise BadRequest("this sign-in has expired; please start again")
    if challenge.confirmed_at is None or challenge.phone_e164 is None:
        return None
    challenge.used_at = utcnow()
    return await upsert_phone_user(db, challenge.phone_e164)

"""One-time passcodes for mobile sign-in."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import OtpChallenge, User, utcnow
from ..errors import BadRequest, TooManyRequests
from .sessions import aware
from .sms import SmsSender
from .users import upsert_phone_user

OTP_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 5
PHONE_WINDOW, PHONE_LIMIT = timedelta(minutes=15), 3
IP_WINDOW, IP_LIMIT = timedelta(hours=1), 20
RETENTION = timedelta(days=1)

_INDIAN_MOBILE = re.compile(r"^(?:\+?91|0)?([6-9]\d{9})$")
_INVALID_CODE = "The code is wrong or has expired. Please request a new one."


def normalize_phone(raw: str) -> str:
    match = _INDIAN_MOBILE.match(re.sub(r"[\s\-()]", "", raw))
    if not match:
        raise BadRequest("enter a valid 10-digit Indian mobile number")
    return f"+91{match.group(1)}"


def _code_hash(secret: str, phone: str, code: str) -> str:
    return hmac.new(secret.encode(), f"{phone}|{code}".encode(), hashlib.sha256).hexdigest()


async def request_otp(
    db: AsyncSession, *, secret: str, sender: SmsSender, phone_raw: str, ip: str | None
) -> None:
    phone = normalize_phone(phone_raw)
    now = utcnow()
    await db.execute(delete(OtpChallenge).where(OtpChallenge.created_at < now - RETENTION))

    recent_for_phone = await db.scalar(
        select(func.count())
        .select_from(OtpChallenge)
        .where(OtpChallenge.phone_e164 == phone, OtpChallenge.created_at >= now - PHONE_WINDOW)
    )
    recent_for_ip = (
        await db.scalar(
            select(func.count())
            .select_from(OtpChallenge)
            .where(OtpChallenge.ip == ip, OtpChallenge.created_at >= now - IP_WINDOW)
        )
        if ip
        else 0
    )
    if recent_for_phone >= PHONE_LIMIT or recent_for_ip >= IP_LIMIT:
        raise TooManyRequests("too many codes requested; please wait a few minutes and try again")

    code = f"{secrets.randbelow(10**6):06d}"
    db.add(OtpChallenge(phone_e164=phone, code_hash=_code_hash(secret, phone, code), expires_at=now + OTP_TTL, ip=ip))
    await db.commit()
    minutes = int(OTP_TTL.total_seconds() // 60)
    await sender.send(
        phone, f"{code} is your Saathi sign-in code. It expires in {minutes} minutes. Never share it with anyone."
    )


async def verify_otp(db: AsyncSession, *, secret: str, phone_raw: str, code: str) -> User:
    """Check the code and sign in (creating the account on first use)."""
    return await upsert_phone_user(db, await consume_otp(db, secret=secret, phone_raw=phone_raw, code=code))


async def consume_otp(db: AsyncSession, *, secret: str, phone_raw: str, code: str) -> str:
    """Check the code, mark it used, and return the verified number in E.164 form."""
    phone = normalize_phone(phone_raw)
    challenge = await db.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.phone_e164 == phone, OtpChallenge.consumed_at.is_(None))
        .order_by(OtpChallenge.created_at.desc())
        .limit(1)
    )
    now = utcnow()
    if challenge is None or aware(challenge.expires_at) <= now or challenge.attempts >= MAX_ATTEMPTS:
        raise BadRequest(_INVALID_CODE)

    challenge.attempts += 1
    if not hmac.compare_digest(challenge.code_hash, _code_hash(secret, phone, code.strip())):
        await db.commit()
        raise BadRequest(_INVALID_CODE)

    challenge.consumed_at = now
    return phone

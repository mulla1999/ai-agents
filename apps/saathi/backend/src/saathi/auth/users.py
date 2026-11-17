"""Finding or creating the user behind a sign-in identity."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import AuthIdentity, AuthProvider, Role, User
from ..errors import Conflict


async def _user_for_identity(db: AsyncSession, provider: AuthProvider, subject: str) -> User | None:
    identity = await db.scalar(
        select(AuthIdentity).where(AuthIdentity.provider == provider, AuthIdentity.subject == subject)
    )
    return await db.get(User, identity.user_id) if identity else None


async def upsert_google_user(
    db: AsyncSession, *, subject: str, email: str, name: str | None, admin_emails: frozenset[str]
) -> User:
    """Called only with a verified email from a validated Google ID token."""
    email = email.lower()
    user = await _user_for_identity(db, AuthProvider.GOOGLE, subject)
    if user is None:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, display_name=name, role=Role.CITIZEN)
            db.add(user)
            await db.flush()
        db.add(AuthIdentity(user_id=user.id, provider=AuthProvider.GOOGLE, subject=subject))
    if email in admin_emails and user.role is not Role.ADMIN:
        user.role = Role.ADMIN
    if name and not user.display_name:
        user.display_name = name
    return user


async def sign_in_methods(db: AsyncSession, user: User) -> list[str]:
    rows = await db.scalars(select(AuthIdentity.provider).where(AuthIdentity.user_id == user.id))
    return sorted(str(provider) for provider in rows)


async def link_identity(db: AsyncSession, user: User, provider: AuthProvider, subject: str) -> None:
    """Add a verified sign-in method to ``user``. Refuses one that already belongs to someone else."""
    owner = await _user_for_identity(db, provider, subject)
    if owner is not None:
        if owner.id != user.id:
            raise Conflict("this sign-in method is already used by another account")
        return
    if provider is AuthProvider.PHONE:
        holder = await db.scalar(select(User).where(User.phone_e164 == subject))
        if holder is not None and holder.id != user.id:
            raise Conflict("this mobile number is already used by another account")
        user.phone_e164 = subject
    db.add(AuthIdentity(user_id=user.id, provider=provider, subject=subject))


async def upsert_phone_user(db: AsyncSession, phone_e164: str) -> User:
    """Called only after the OTP for ``phone_e164`` was verified."""
    user = await _user_for_identity(db, AuthProvider.PHONE, phone_e164)
    if user is None:
        user = User(phone_e164=phone_e164, role=Role.CITIZEN)
        db.add(user)
        await db.flush()
        db.add(AuthIdentity(user_id=user.id, provider=AuthProvider.PHONE, subject=phone_e164))
    return user

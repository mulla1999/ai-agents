"""Load and save the singleton profile, preferences and automation policy.

The mode never changes implicitly: switching to automatic needs an explicit confirmation phrase,
is audited, and a stored policy that fails validation falls back to safe defaults (supervised).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import AutomationPolicyRow, UserProfile
from ..domain import ApplicationMode, AutomationPolicy, Preferences, Profile
from .audit import record

log = logging.getLogger(__name__)
M = TypeVar("M", Profile, Preferences, AutomationPolicy)


def _load(model: type[M], data: dict[str, Any] | None, what: str, user_id: int) -> M:
    """Load stored settings. A field that no longer validates falls back to its default on its own;
    everything else is kept (it used to reset the whole profile, preferences or policy)."""
    data = dict(data or {})
    for _ in range(len(data) + 1):
        try:
            return model.model_validate(data, context={"stored": True})
        except ValidationError as exc:
            bad = {str(e["loc"][0]) for e in exc.errors() if e["loc"]} & data.keys()
            if not bad:
                break
            log.warning("user %s: stored %s fields %s are invalid; using defaults for them", user_id, what, sorted(bad))
            for key in bad:
                data.pop(key)
    return model()

AUTOMATIC_CONFIRMATION = "ENABLE AUTOMATIC MODE"


class PolicyError(ValueError):
    pass


@dataclass
class PolicyState:
    policy: AutomationPolicy
    paused: bool
    emergency_stop: bool
    stop_reason: str | None


async def _profile_row(db: AsyncSession, user_id: int) -> UserProfile:
    row = await db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    if row is None:
        row = UserProfile(user_id=user_id, profile=Profile().model_dump(mode="json"),
                          preferences=Preferences().model_dump(mode="json"))
        db.add(row)
        await db.flush()
    return row


async def _policy_row(db: AsyncSession, user_id: int) -> AutomationPolicyRow:
    row = await db.scalar(select(AutomationPolicyRow).where(AutomationPolicyRow.user_id == user_id))
    if row is None:
        row = AutomationPolicyRow(user_id=user_id, policy=AutomationPolicy().model_dump(mode="json"))
        db.add(row)
        await db.flush()
    return row


async def get_profile(db: AsyncSession, user_id: int) -> Profile:
    row = await _profile_row(db, user_id)
    return _load(Profile, row.profile, "profile", user_id)


async def get_preferences(db: AsyncSession, user_id: int) -> Preferences:
    row = await _profile_row(db, user_id)
    return _load(Preferences, row.preferences, "preferences", user_id)


async def save_profile(db: AsyncSession, user_id: int, profile: Profile) -> None:
    row = await _profile_row(db, user_id)
    row.profile = profile.model_dump(mode="json")
    await record(db, user_id, "config.profile", "profile updated", actor="user")


async def save_preferences(db: AsyncSession, user_id: int, preferences: Preferences) -> None:
    row = await _profile_row(db, user_id)
    row.preferences = preferences.model_dump(mode="json")
    await record(db, user_id, "config.preferences", "job preferences updated", actor="user")


async def get_policy_state(db: AsyncSession, user_id: int) -> PolicyState:
    row = await _policy_row(db, user_id)
    policy = _load(AutomationPolicy, row.policy, "policy", user_id)  # defaults are safe: supervised, no auto-send
    return PolicyState(policy, row.paused, row.emergency_stop, row.stop_reason)


async def save_policy(db: AsyncSession, user_id: int, policy: AutomationPolicy, *, confirmation: str | None = None) -> None:
    row = await _policy_row(db, user_id)
    previous = _load(AutomationPolicy, row.policy, "policy", user_id)
    if policy.mode is ApplicationMode.AUTOMATIC and previous.mode is not ApplicationMode.AUTOMATIC:
        if confirmation != AUTOMATIC_CONFIRMATION:
            raise PolicyError(f"to enable automatic applications, confirm with the phrase '{AUTOMATIC_CONFIRMATION}'")
        await record(db, user_id, "config.mode", "automatic application mode ENABLED", actor="user", level="warning")
    if policy.mode is ApplicationMode.SUPERVISED and previous.mode is ApplicationMode.AUTOMATIC:
        await record(db, user_id, "config.mode", "returned to supervised mode", actor="user")
    if policy.auto_send_outreach and not previous.auto_send_outreach:
        if confirmation != AUTOMATIC_CONFIRMATION:
            raise PolicyError(f"to enable automatic recruiter emails, confirm with the phrase '{AUTOMATIC_CONFIRMATION}'")
        await record(db, user_id, "config.outreach", "automatic recruiter emails ENABLED", actor="user", level="warning")
    changed = {k: v for k, v in policy.model_dump(mode="json").items() if previous.model_dump(mode="json").get(k) != v}
    row.policy = policy.model_dump(mode="json")
    await record(db, user_id, "config.policy", "automation policy updated", actor="user", details={"changed": changed})


async def set_paused(db: AsyncSession, user_id: int, paused: bool) -> None:
    row = await _policy_row(db, user_id)
    row.paused = paused
    await record(db, user_id, "automation.pause" if paused else "automation.resume",
                 "automation paused" if paused else "automation resumed", actor="user")


async def set_emergency_stop(db: AsyncSession, user_id: int, stopped: bool, reason: str | None = None, *,
                             actor: str = "user") -> None:
    row = await _policy_row(db, user_id)
    row.emergency_stop = stopped
    row.stop_reason = reason if stopped else None
    await record(db, user_id, "automation.emergency_stop" if stopped else "automation.stop_cleared",
                 f"emergency stop {'engaged' if stopped else 'cleared'}" + (f": {reason}" if reason else ""),
                 actor=actor, level="warning" if stopped else "info")

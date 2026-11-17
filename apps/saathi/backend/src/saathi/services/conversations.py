"""Database-backed conversation store for the web chat. The session key is the citizen ID."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from agents_core.llm import Message
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..agent.session import MAX_HISTORY_MESSAGES, Session
from ..db import Channel, ChatMessage, Citizen, Conversation, utcnow
from ..errors import NotFound
from ..profile import PROFILE_FIELDS, UserProfile, age_on

log = logging.getLogger(__name__)


def profile_from_json(data: dict[str, Any] | None) -> UserProfile:
    """Load a stored profile, dropping any field that no longer validates (e.g. after a schema change)."""
    try:
        return UserProfile.model_validate(data or {})
    except ValidationError:
        profile = UserProfile()
        for name, value in (data or {}).items():
            if name in PROFILE_FIELDS:
                try:
                    setattr(profile, name, value)
                except ValidationError:
                    log.info("dropped invalid stored value for profile field %s", name)
        return profile


def profile_to_json(profile: UserProfile) -> dict[str, Any]:
    return profile.model_dump(mode="json", exclude_none=True)


class DbSessionStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], channel: Channel = Channel.WEB) -> None:
        self._sessionmaker = sessionmaker
        self._channel = channel

    async def get(self, user_id: str) -> Session:
        async with self._sessionmaker() as db:
            citizen = await db.get(Citizen, uuid.UUID(user_id))
            if citizen is None:
                raise NotFound("citizen not found")
            profile = profile_from_json(citizen.profile)
            if citizen.date_of_birth is not None:
                profile.age = age_on(citizen.date_of_birth)
            session = Session(user_id, profile=profile, language=citizen.language)
            conversation = await self._conversation(db, citizen.id)
            if conversation is not None:
                session.restore_state(conversation.state)
                recent = (
                    await db.scalars(
                        select(ChatMessage)
                        .where(ChatMessage.conversation_id == conversation.id)
                        .order_by(ChatMessage.created_at.desc())
                        .limit(MAX_HISTORY_MESSAGES)
                    )
                ).all()
                session.history = [Message(m.role, m.content) for m in reversed(recent)]
        return session

    async def save(self, session: Session) -> None:
        async with self._sessionmaker() as db, db.begin():
            citizen = await db.get(Citizen, uuid.UUID(session.user_id))
            if citizen is None:  # erased while the turn was running
                return
            citizen.profile = profile_to_json(session.profile)
            citizen.language = session.language
            conversation = await self._conversation(db, citizen.id)
            if conversation is None:
                conversation = Conversation(citizen_id=citizen.id, channel=self._channel)
                db.add(conversation)
                await db.flush()
            conversation.state = session.state()
            conversation.updated_at = utcnow()
            start = utcnow()
            for offset, message in enumerate(session.new_messages):
                db.add(
                    ChatMessage(
                        conversation_id=conversation.id,
                        role=message.role,
                        content=message.content,
                        created_at=start + timedelta(microseconds=offset),
                    )
                )
        session.new_messages.clear()

    async def delete(self, user_id: str) -> None:
        """"Delete my data" said in chat: clear the profile and the conversation; the account stays."""
        async with self._sessionmaker() as db, db.begin():
            citizen = await db.get(Citizen, uuid.UUID(user_id))
            if citizen is None:
                return
            citizen.profile = {}
            citizen.language = None
            await db.execute(delete(Conversation).where(Conversation.citizen_id == citizen.id))

    async def _conversation(self, db: AsyncSession, citizen_id: uuid.UUID) -> Conversation | None:
        return await db.scalar(
            select(Conversation).where(Conversation.citizen_id == citizen_id, Conversation.channel == self._channel)
        )

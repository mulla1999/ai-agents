"""Chat quotas: per citizen (web and WhatsApp together) and for the whole service.

Counts come from the stored user messages, so every worker sees the same numbers. Turns for one
citizen are serialised by the chat lease, so a burst from one person cannot slip past the count.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import ChatMessage, Conversation, utcnow
from ..errors import TooManyRequests

log = logging.getLogger(__name__)

PERSONAL_LIMIT_MESSAGE = "You have sent a lot of messages. Please wait a little and try again."
SERVICE_LIMIT_MESSAGE = "Saathi is very busy right now. Please try again later."


async def check_chat_quota(db: AsyncSession, citizen_id: uuid.UUID, settings: Settings) -> None:
    """Raise ``TooManyRequests`` if this citizen, or the service as a whole, is over its chat limit."""
    now = utcnow()
    since_day = now - timedelta(days=1)
    mine = (
        select(func.count())
        .select_from(ChatMessage)
        .join(Conversation, ChatMessage.conversation_id == Conversation.id)
        .where(Conversation.citizen_id == citizen_id, ChatMessage.role == "user")
    )
    if await db.scalar(mine.where(ChatMessage.created_at >= now - timedelta(minutes=10))) >= (
        settings.chat_limit_per_10_minutes
    ) or await db.scalar(mine.where(ChatMessage.created_at >= since_day)) >= settings.chat_limit_per_day:
        raise TooManyRequests(PERSONAL_LIMIT_MESSAGE)

    if settings.chat_global_limit_per_day > 0:
        total = await db.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.role == "user", ChatMessage.created_at >= since_day)
        )
        if total >= settings.chat_global_limit_per_day:
            log.warning("global daily chat limit reached (%d messages)", total)
            raise TooManyRequests(SERVICE_LIMIT_MESSAGE)

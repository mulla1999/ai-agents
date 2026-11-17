"""Web chat with Saathi for a citizen record."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from sqlalchemy import select

from ..auth.deps import DB, CurrentUser
from ..db import Channel, ChatMessage, Conversation
from ..errors import Unavailable
from ..services.access import load_citizen, require_consent
from ..services.conversations import profile_to_json
from .schemas import ChatIn, ChatOut, MessageOut

router = APIRouter(prefix="/api/citizens/{citizen_id}", tags=["chat"])


@router.get("/messages")
async def messages(citizen_id: uuid.UUID, user: CurrentUser, db: DB, limit: int = 100) -> list[MessageOut]:
    citizen = await load_citizen(db, user, citizen_id, action="read_messages")
    rows = (
        await db.scalars(
            select(ChatMessage)
            .join(Conversation, ChatMessage.conversation_id == Conversation.id)
            .where(Conversation.citizen_id == citizen.id, Conversation.channel == Channel.WEB)
            .order_by(ChatMessage.created_at.desc())
            .limit(min(max(limit, 1), 500))
        )
    ).all()
    await db.commit()
    return [MessageOut.model_validate(m) for m in reversed(rows)]


@router.post("/chat")
async def chat(citizen_id: uuid.UUID, body: ChatIn, request: Request, user: CurrentUser, db: DB) -> ChatOut:
    agent = request.app.state.web_agent
    if agent is None:
        raise Unavailable("chat is not configured on this server (no LLM provider)")
    citizen = await load_citizen(db, user, citizen_id, action="chat")
    require_consent(citizen)
    await db.commit()  # release the connection before the (slow) LLM calls

    key = str(citizen.id)
    reply = await agent.handle(key, body.message)
    return ChatOut(reply=reply, profile=profile_to_json(await agent.profile(key)))

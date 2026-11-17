"""The chat assistant: conversations, messages and confirmations. Everything is scoped to the
signed-in user; another user's conversation or action is reported as not found."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from ..db import ChatAction, ChatConversation, ChatMessage, utcnow
from ..errors import ServiceError
from ..services.assistant import agent
from ..services.assistant.guardrails import MAX_CHARS
from ..services.assistant.tools import Ctx
from .deps import DB, URT, iso

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


async def _conversation(db, user_id: int, cid: int) -> ChatConversation:  # noqa: ANN001
    row = await db.get(ChatConversation, cid)
    if row is None or row.user_id != user_id:
        raise ServiceError("not_found", "conversation not found", 404)
    return row


def _conv_out(c: ChatConversation) -> dict:
    return {"id": c.id, "title": c.title, "created_at": iso(c.created_at), "updated_at": iso(c.updated_at)}


async def _messages_out(db, rows: list[ChatMessage]) -> list[dict]:  # noqa: ANN001
    ids = [r.data.get("action_id") for r in rows if (r.data or {}).get("action_id")]
    actions = {a.id: a for a in (await db.scalars(select(ChatAction).where(ChatAction.id.in_(ids))))} if ids else {}
    return [agent.message_out(r, actions) for r in rows]


@router.get("/status")
async def status(rt: URT) -> dict:
    return {"ai": rt.llm is not None, "ai_provider": rt.llm.name if rt.llm else None, "ai_error": rt.llm_error,
            "ai_verified": rt.llm_verified,
            "web_search": "websearch" in rt.credentials, "max_chars": MAX_CHARS}


@router.get("/conversations")
async def conversations(db: DB, rt: URT) -> list[dict]:
    rows = (await db.scalars(select(ChatConversation).where(ChatConversation.user_id == rt.user_id)
                             .order_by(ChatConversation.updated_at.desc()).limit(50))).all()
    return [_conv_out(c) for c in rows]


@router.post("/conversations", status_code=201)
async def new_conversation(db: DB, rt: URT) -> dict:
    row = ChatConversation(user_id=rt.user_id)
    db.add(row)
    await db.commit()
    return _conv_out(row)


@router.get("/conversations/{cid}")
async def conversation(cid: int, db: DB, rt: URT) -> dict:
    conv = await _conversation(db, rt.user_id, cid)
    rows = (await db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == cid).order_by(ChatMessage.id)
                             .limit(400))).all()
    return {**_conv_out(conv), "messages": await _messages_out(db, list(rows))}


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: int, db: DB, rt: URT) -> dict:
    conv = await _conversation(db, rt.user_id, cid)
    await db.execute(delete(ChatAction).where(ChatAction.conversation_id == cid))
    await db.execute(delete(ChatMessage).where(ChatMessage.conversation_id == cid))
    await db.delete(conv)
    await db.commit()
    return {"deleted": True}


class MessageBody(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_CHARS * 2)  # the guardrail gives the friendly message


@router.post("/conversations/{cid}/messages")
async def send_message(cid: int, body: MessageBody, request: Request, db: DB, rt: URT) -> dict:
    limiter = request.app.state.runtime.limiter
    if not await limiter.hit(f"assistant:{rt.user_id}", 20, 300) or not await limiter.hit(f"assistant-day:{rt.user_id}", 300, 86400):
        raise ServiceError("rate_limited", "you're sending messages very fast; wait a minute and try again", 429)
    conv = await _conversation(db, rt.user_id, cid)
    rows = await agent.handle(Ctx(db, rt, conv.id, limiter), conv, body.text)
    return {"conversation": _conv_out(conv), "messages": await _messages_out(db, rows)}


async def _action(db, user_id: int, aid: int) -> ChatAction:  # noqa: ANN001
    row = await db.get(ChatAction, aid)
    if row is None or row.user_id != user_id:
        raise ServiceError("not_found", "action not found", 404)
    return row


@router.post("/actions/{aid}/confirm")
async def confirm(aid: int, request: Request, db: DB, rt: URT) -> dict:
    action = await _action(db, rt.user_id, aid)
    if action.status != "pending":
        raise ServiceError("bad_state", f"this action is already {action.status}", 409)
    conv = await _conversation(db, rt.user_id, action.conversation_id)
    turn =await agent.confirm(Ctx(db, rt, conv.id, request.app.state.runtime.limiter), action)
    msg = ChatMessage(conversation_id=conv.id, user_id=rt.user_id, role="assistant", content=turn.reply,
                      data={"suggestions": turn.suggestions})
    db.add(msg)
    conv.updated_at = utcnow()
    await db.commit()
    await db.refresh(action)
    return {"action": agent.action_out(action), "messages": await _messages_out(db, [msg])}


@router.post("/actions/{aid}/cancel")
async def cancel(aid: int, db: DB, rt: URT) -> dict:
    action = await _action(db, rt.user_id, aid)
    if action.status == "pending":
        action.status, action.decided_at = "cancelled", utcnow()
        await db.commit()
    return {"action": agent.action_out(action)}

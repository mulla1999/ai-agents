"""WhatsApp Business Cloud API webhook.

Every POST is authenticated with the ``X-Hub-Signature-256`` HMAC Meta sends; unsigned or wrongly
signed requests are rejected. Message text and phone numbers are never logged.

Agents plug in with an ``on_message`` callback that receives the parsed message (including the
sender's number and any voice-note media id) and returns the reply text. ``text_only`` adapts a
simple ``handle(user_id, text)`` agent that should never see raw phone numbers.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

log = logging.getLogger(__name__)

MAX_WHATSAPP_TEXT = 4096
TEXT_ONLY_REPLY = (
    "For now I can only read text messages. Please type your message.\n"
    "अभी मैं केवल लिखे हुए संदेश पढ़ सकता हूँ। कृपया अपना संदेश टाइप करें।"
)


class MessageHandler(Protocol):
    async def handle(self, user_id: str, text: str) -> str: ...


@dataclass(frozen=True)
class IncomingMessage:
    message_id: str
    sender: str  # WhatsApp ID: the phone number in international format without "+"
    type: str
    text: str | None
    media_id: str | None = None  # set for audio / voice notes
    mime_type: str | None = None
    # Set when the person tapped a reply button or list row; ``text`` then holds its title.
    reply_id: str | None = None


MessageCallback = Callable[[IncomingMessage], Awaitable[str | None]]
# Returns False if the message id was already accepted (by this or any other worker).
DedupCallback = Callable[[str], Awaitable[bool]]
MAX_BUTTONS, MAX_BUTTON_TITLE, MAX_INTERACTIVE_BODY = 3, 20, 1024


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def parse_messages(payload: dict[str, Any]) -> list[IncomingMessage]:
    messages = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            for msg in (change.get("value") or {}).get("messages") or []:
                if not msg.get("id") or not msg.get("from"):
                    continue
                kind = msg.get("type", "")
                text = (msg.get("text") or {}).get("body") if kind == "text" else None
                media = (msg.get("audio") or {}) if kind == "audio" else {}
                reply_id = None
                if kind == "interactive":
                    interactive = msg.get("interactive") or {}
                    choice = interactive.get("button_reply") or interactive.get("list_reply") or {}
                    reply_id, text = choice.get("id"), choice.get("title")
                messages.append(
                    IncomingMessage(
                        msg["id"], msg["from"], kind, text, media.get("id"), media.get("mime_type"), reply_id
                    )
                )
    return messages


def text_only(handler: MessageHandler, *, key_secret: str) -> MessageCallback:
    """Adapt a ``handle(user_id, text)`` agent: users are keyed by a keyed hash of their number."""

    async def on_message(message: IncomingMessage) -> str:
        if message.text is None:
            return TEXT_ONLY_REPLY
        user_key = hmac.new(key_secret.encode(), message.sender.encode(), hashlib.sha256).hexdigest()
        return await handler.handle(user_key, message.text)

    return on_message


class WhatsAppClient:
    def __init__(self, *, access_token: str, phone_number_id: str, graph_version: str, http: httpx.AsyncClient):
        self._graph = f"https://graph.facebook.com/{graph_version}"
        self._phone_number_id = phone_number_id
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._http = http

    async def send_text(self, to: str, body: str) -> None:
        response = await self._http.post(
            f"{self._graph}/{self._phone_number_id}/messages",
            headers=self._headers,
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": body[:MAX_WHATSAPP_TEXT]},
            },
        )
        response.raise_for_status()

    async def send_buttons(self, to: str, body: str, buttons: Sequence[tuple[str, str]]) -> None:
        """Send up to three reply buttons as (id, title); the tap arrives as ``reply_id``."""
        if not 1 <= len(buttons) <= MAX_BUTTONS:
            raise ValueError(f"WhatsApp allows 1 to {MAX_BUTTONS} reply buttons")
        response = await self._http.post(
            f"{self._graph}/{self._phone_number_id}/messages",
            headers=self._headers,
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body[:MAX_INTERACTIVE_BODY]},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": bid, "title": title[:MAX_BUTTON_TITLE]}}
                            for bid, title in buttons
                        ]
                    },
                },
            },
        )
        response.raise_for_status()

    async def download_media(self, media_id: str, *, max_bytes: int = 16 * 1024 * 1024) -> tuple[bytes, str]:
        """Fetch an incoming media file (e.g. a voice note). Returns (content, mime type)."""
        meta = await self._http.get(f"{self._graph}/{media_id}", headers=self._headers)
        meta.raise_for_status()
        info = meta.json()
        if int(info.get("file_size") or 0) > max_bytes:
            raise ValueError("media file too large")
        content = await self._http.get(info["url"], headers=self._headers)
        content.raise_for_status()
        if len(content.content) > max_bytes:
            raise ValueError("media file too large")
        return content.content, info.get("mime_type") or "application/octet-stream"

    async def send_audio(self, to: str, audio: bytes, mime_type: str) -> None:
        """Upload audio and send it as a voice message."""
        upload = await self._http.post(
            f"{self._graph}/{self._phone_number_id}/media",
            headers=self._headers,
            data={"messaging_product": "whatsapp", "type": mime_type},
            files={"file": ("reply", audio, mime_type)},
        )
        upload.raise_for_status()
        response = await self._http.post(
            f"{self._graph}/{self._phone_number_id}/messages",
            headers=self._headers,
            json={"messaging_product": "whatsapp", "to": to, "type": "audio", "audio": {"id": upload.json()["id"]}},
        )
        response.raise_for_status()


class _RecentIds:
    """Meta retries deliveries; remember recent message ids so each is answered once."""

    def __init__(self, capacity: int = 10_000) -> None:
        self._ids: OrderedDict[str, None] = OrderedDict()
        self._capacity = capacity

    def seen(self, message_id: str) -> bool:
        if message_id in self._ids:
            return True
        self._ids[message_id] = None
        if len(self._ids) > self._capacity:
            self._ids.popitem(last=False)
        return False


def build_router(
    *,
    verify_token: str,
    app_secret: str,
    on_message: MessageCallback,
    client: WhatsAppClient,
    is_new_message: DedupCallback | None = None,
) -> APIRouter:
    """``is_new_message`` adds a shared (e.g. database) duplicate check for multi-worker deployments;
    without it, duplicates are only caught within this process."""
    router = APIRouter(prefix="/webhooks/whatsapp")
    recent = _RecentIds()

    async def process(message: IncomingMessage) -> None:
        try:
            reply = await on_message(message)
            if reply:
                await client.send_text(message.sender, reply)
        except Exception:
            log.exception("failed to process WhatsApp message %s", message.message_id)

    @router.get("", response_class=PlainTextResponse)
    async def verify(
        mode: str = Query("", alias="hub.mode"),
        token: str = Query("", alias="hub.verify_token"),
        challenge: str = Query("", alias="hub.challenge"),
    ) -> str:
        if mode == "subscribe" and hmac.compare_digest(token.encode(), verify_token.encode()):
            return challenge
        raise HTTPException(status_code=403)

    @router.post("")
    async def receive(request: Request, background: BackgroundTasks) -> dict[str, str]:
        body = await request.body()
        if not verify_signature(app_secret, body, request.headers.get("x-hub-signature-256")):
            raise HTTPException(status_code=403)
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(status_code=400) from None
        # Reply after returning 200: Meta expects a fast acknowledgement.
        for message in parse_messages(payload):
            if recent.seen(message.message_id):
                continue
            if is_new_message is None or await is_new_message(message.message_id):
                background.add_task(process, message)
        return {"status": "ok"}

    return router

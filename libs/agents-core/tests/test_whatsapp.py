import hashlib
import hmac
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents_core.channels.whatsapp import TEXT_ONLY_REPLY, build_router, parse_messages, text_only, verify_signature

SECRET = "app-secret"


class FakeHandler:
    def __init__(self):
        self.received: list[tuple[str, str]] = []

    async def handle(self, user_id: str, text: str) -> str:
        self.received.append((user_id, text))
        return f"echo: {text}"


class FakeClient:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, to: str, body: str) -> None:
        self.sent.append((to, body))


def make_client():
    handler, wa = FakeHandler(), FakeClient()
    app = FastAPI()
    on_message = text_only(handler, key_secret=SECRET)
    app.include_router(build_router(verify_token="vt", app_secret=SECRET, on_message=on_message, client=wa))
    return TestClient(app), handler, wa


def payload(msg_id: str, msg: dict) -> bytes:
    body = {"entry": [{"changes": [{"value": {"messages": [{"id": msg_id, "from": "919999999999", **msg}]}}]}]}
    return json.dumps(body).encode()


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature():
    assert verify_signature(SECRET, b"x", sign(b"x"))
    assert not verify_signature(SECRET, b"x", sign(b"y"))
    assert not verify_signature(SECRET, b"x", None)


def test_subscription_handshake():
    client, _, _ = make_client()
    params = {"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"}
    assert client.get("/webhooks/whatsapp", params=params).text == "42"
    params["hub.verify_token"] = "wrong"
    assert client.get("/webhooks/whatsapp", params=params).status_code == 403


def test_rejects_unsigned_post():
    client, handler, _ = make_client()
    body = payload("m1", {"type": "text", "text": {"body": "hi"}})
    assert client.post("/webhooks/whatsapp", content=body).status_code == 403
    assert client.post("/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": "sha256=bad"}).status_code == 403
    assert handler.received == []


def test_text_message_is_answered_once_with_hashed_user_id():
    client, handler, wa = make_client()
    body = payload("m1", {"type": "text", "text": {"body": "hi"}})
    for _ in range(2):  # Meta retry
        assert client.post("/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sign(body)}).status_code == 200

    assert len(handler.received) == 1
    user_id, text = handler.received[0]
    assert text == "hi" and "919999999999" not in user_id
    assert wa.sent == [("919999999999", "echo: hi")]


def test_non_text_message_gets_text_only_notice():
    client, handler, wa = make_client()
    body = payload("m2", {"type": "audio", "audio": {"id": "a1"}})
    client.post("/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sign(body)})
    assert handler.received == []
    assert wa.sent == [("919999999999", TEXT_ONLY_REPLY)]


def test_parse_voice_note_keeps_media_id():
    body = json.loads(payload("m3", {"type": "audio", "audio": {"id": "media-1", "mime_type": "audio/ogg; codecs=opus"}}))
    [message] = parse_messages(body)
    assert message.text is None and message.media_id == "media-1" and message.mime_type.startswith("audio/ogg")

from datetime import timedelta

import httpx
import pytest
from agents_core.channels.whatsapp import IncomingMessage
from pydantic import SecretStr
from sqlalchemy import update

from saathi.app import create_app
from saathi.auth.whatsapp_login import login_code
from saathi.db import WhatsAppLogin, utcnow
from saathi.services.whatsapp import LOGIN_CONFIRMED, LOGIN_UNKNOWN

BOT = "919000000000"


@pytest.fixture
def wa_app(settings, sessionmaker, llm, sms):
    configured = settings.model_copy(
        update={
            "whatsapp_verify_token": SecretStr("vt"),
            "whatsapp_app_secret": SecretStr("as"),
            "whatsapp_access_token": SecretStr("at"),
            "whatsapp_phone_number_id": "123",
            "whatsapp_login_number": BOT,
        }
    )
    return create_app(configured, sessionmaker=sessionmaker, llm=llm, sms_sender=sms)


async def browser(app) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    client.headers["x-csrf-token"] = (await client.get("/api/auth/csrf")).json()["csrf_token"]
    return client


def send(app, text: str, sender: str = "919876500001"):
    return app.state.whatsapp_handler(IncomingMessage("m", sender, "text", text))


async def test_sign_in_with_whatsapp(wa_app):
    web = await browser(wa_app)
    assert (await web.get("/api/auth/config")).json()["whatsapp_login_enabled"] is True

    start = (await web.post("/api/auth/whatsapp/start")).json()
    assert start["link"] == f"https://wa.me/{BOT}?text=LOGIN%20{start['code']}"
    assert (await web.post("/api/auth/whatsapp/poll")).json() == {"status": "pending", "user": None}

    assert await send(wa_app, f"login {start['code']}") == LOGIN_CONFIRMED

    done = (await web.post("/api/auth/whatsapp/poll")).json()
    assert done["status"] == "signed_in" and done["user"]["sign_in_methods"] == ["phone"]
    assert (await web.get("/api/auth/me")).json()["phone"] == "+91 ******0001"
    # Signing in is not consent: the person still has to agree before data is collected.
    assert (await web.get("/api/me/citizen")).json()["consent_at"] is None
    # The sign-in cannot be collected twice.
    assert (await web.post("/api/auth/whatsapp/poll")).status_code == 400


async def test_only_the_starting_browser_can_collect_the_session(wa_app):
    victim_browser, attacker = await browser(wa_app), await browser(wa_app)
    start = (await victim_browser.post("/api/auth/whatsapp/start")).json()
    await send(wa_app, f"LOGIN {start['code']}")
    assert (await attacker.post("/api/auth/whatsapp/poll")).status_code == 400  # no cookie, no session
    assert (await attacker.get("/api/auth/me")).status_code == 401


async def test_wrong_and_expired_codes(wa_app, sessionmaker):
    web = await browser(wa_app)
    start = (await web.post("/api/auth/whatsapp/start")).json()
    wrong = "000000" if start["code"] != "000000" else "111111"
    assert await send(wa_app, f"LOGIN {wrong}") == LOGIN_UNKNOWN

    async with sessionmaker() as db:
        await db.execute(update(WhatsAppLogin).values(expires_at=utcnow() - timedelta(seconds=1)))
        await db.commit()
    assert await send(wa_app, f"LOGIN {start['code']}") == LOGIN_UNKNOWN
    assert (await web.post("/api/auth/whatsapp/poll")).status_code == 400


async def test_start_is_rate_limited_and_disabled_without_config(wa_app, app):
    web = await browser(wa_app)
    codes = [(await web.post("/api/auth/whatsapp/start")).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429

    plain = await browser(app)  # WhatsApp not configured
    assert (await plain.post("/api/auth/whatsapp/start")).status_code == 404


def test_login_code_parsing():
    assert login_code("LOGIN 123456") == "123456"
    assert login_code(" login-123456 ") == "123456"
    assert login_code("लॉगिन 123456") == "123456"
    assert login_code("my pin is 123456") is None
    assert login_code(None) is None

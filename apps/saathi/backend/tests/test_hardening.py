"""Reply checking, chat quotas, cross-worker locks, WhatsApp consent and de-duplication."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from agents_core.channels.whatsapp import IncomingMessage
from agents_core.llm.testing import ScriptedLLM

from saathi.agent import Agent, InMemorySessionStore
from saathi.agent.guard import unsupported_facts
from saathi.agent.session import LocalLocks
from saathi.app import create_app
from saathi.config import Settings
from saathi.db import ChatLock, utcnow
from saathi.schemes import load_schemes
from saathi.services.locks import DbLeaseLock, LockTimeout
from saathi.services.whatsapp import (
    CONSENT_BUTTONS,
    CONSENT_DECLINED,
    CONSENT_NOTICE,
    CONSENT_NO,
    CONSENT_YES,
    RATE_LIMITED,
    WELCOME,
    claim_message,
)

SCHEMES = load_schemes(Settings().schemes_dir)
DATA = "benefits: Rs 6,000 per year, paid in three instalments of Rs 2,000. Cover of Rs 2,00,000. https://pmkisan.gov.in"


# --- reply guard -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "You get ₹6000 a year in 3 parts of ₹2,000.",
        "बीमा 2 लाख रुपये का है।",  # same value as Rs 2,00,000
        "बीमा ₹२,००,००० का है।",  # Devanagari digits
        "Apply at https://pmkisan.gov.in/NewFarmer.aspx or www.pmkisan.gov.in",
        "You must be 18 to 40 years old; 1 Feb 2019 is the cut-off.",  # small numbers are not checked
        "It ran from 2019 - 2024 in 12 - 15 districts.",  # ranges are not phone numbers
    ],
)
def test_guard_accepts_facts_from_the_data(reply):
    assert unsupported_facts(reply, DATA) == []


@pytest.mark.parametrize(
    ("reply", "problem"),
    [
        ("You will get ₹8,000 every year.", "number 8000"),
        ("आपको 3 लाख मिलेंगे।", "number 300000"),
        ("Call the helpline 155261 for help.", "number 155261"),
        ("Call 9876543210.", "number 9876543210"),
        ("Toll-free: 1800-180-1551", "number 18001801551"),
        ("Call +91 98765 43210", "number 919876543210"),
        ("Register at pmkisan-help.com", "website pmkisan-help.com"),
        ("See https://pm-kisan.in/apply", "website pm-kisan.in"),
    ],
)
def test_guard_flags_invented_facts(reply, problem):
    assert problem in unsupported_facts(reply, DATA)


class SequenceLLM(ScriptedLLM):
    """Returns the given text replies in order (the last one repeats)."""

    def __init__(self, json_replies, texts):
        super().__init__(json_replies)
        self.texts = list(texts)

    async def complete(self, messages, *, json_output=False):
        if json_output:
            return await super().complete(messages, json_output=True)
        self.calls.append((list(messages), False))
        return self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]


FULL_FARMER = {
    "language": "English",
    "updates": {
        "state": "bihar", "age": 32, "gender": "male", "occupation": "farmer", "has_bank_account": True,
        "owns_cultivable_land": True, "is_income_tax_payer": False, "has_paid_income_tax": False, "is_government_employee": False,
        "plans_new_business": False, "is_studying_post_matric": False, "is_bpl": False, "is_widow": False,
        "has_disability": False, "is_pregnant_or_lactating": False, "residence": "rural", "ration_card": "none",
        "has_pucca_house": True, "has_lpg_connection": True, "land_holding_hectares": 1.0,
        "has_epf_esic_or_nps": False,
    },
}  # fmt: skip


async def test_agent_retries_once_when_the_reply_invents_an_amount():
    llm = SequenceLLM([FULL_FARMER], ["PM-KISAN pays ₹9,999 a year.", "PM-KISAN pays Rs 6,000 a year."])
    agent = Agent(llm, SCHEMES, InMemorySessionStore())

    reply = await agent.handle("u1", "...")

    assert reply == "PM-KISAN pays Rs 6,000 a year."
    retry_prompt = llm.text_prompts()[1]
    assert "CORRECTION" in retry_prompt and "9999" in retry_prompt


async def test_agent_falls_back_to_scheme_data_when_the_model_keeps_inventing():
    llm = SequenceLLM([FULL_FARMER], ["Call 1800-000-0000 to get ₹9,999!"])
    agent = Agent(llm, SCHEMES, InMemorySessionStore())

    reply = await agent.handle("u1", "...")

    assert "9,999" not in reply and "PM-KISAN" in reply and "pmkisan.gov.in" in reply
    assert len(llm.text_prompts()) == 2  # one retry, then the fixed reply


async def test_amounts_the_person_gave_may_be_repeated():
    llm = SequenceLLM(
        [{"language": "English", "updates": {"annual_family_income": 120000}}],
        ["Thanks, a family income of ₹1,20,000 a year. Which state do you live in?"],
    )
    agent = Agent(llm, SCHEMES, InMemorySessionStore())
    assert "1,20,000" in await agent.handle("u1", "we earn 10 hazaar a month")


# --- locks -------------------------------------------------------------------------------------


async def test_local_locks_serialise_and_clean_up():
    locks, order = LocalLocks(), []

    async def turn(name):
        async with locks.hold("u1"):
            order.append(f"{name}-start")
            await asyncio.sleep(0.01)
            order.append(f"{name}-end")

    await asyncio.gather(turn("a"), turn("b"))
    assert order in (["a-start", "a-end", "b-start", "b-end"], ["b-start", "b-end", "a-start", "a-end"])
    assert len(locks) == 0  # no entry left behind per user


async def test_db_lease_lock_is_exclusive_times_out_and_expires(sessionmaker):
    lock = DbLeaseLock(sessionmaker, wait_seconds=0.3)
    async with lock.hold("chat:x"):
        with pytest.raises(LockTimeout):
            async with lock.hold("chat:x"):
                pass
        async with lock.hold("chat:other"):  # other citizens are not blocked
            pass
    async with lock.hold("chat:x"):  # released
        pass

    async with sessionmaker() as db:  # a crashed worker's lease stops counting once it expires
        db.add(ChatLock(key="chat:y", token="dead", expires_at=utcnow() - timedelta(seconds=1)))
        await db.commit()
    async with lock.hold("chat:y"):
        pass


# --- quotas ------------------------------------------------------------------------------------


@pytest.fixture
def strict_settings() -> Settings:
    return Settings(
        _env_file=None, environment="test", cookie_secure=False, chat_limit_per_10_minutes=2, chat_limit_per_day=100
    )


async def _consented_web_chat(client):
    citizen = (await client.get("/api/me/citizen")).json()
    await client.post(f"/api/citizens/{citizen['id']}/consent")
    return f"/api/citizens/{citizen['id']}/chat"


async def test_web_chat_is_rate_limited(strict_settings, sessionmaker, llm, sms, login):
    import httpx

    app = create_app(strict_settings, sessionmaker=sessionmaker, llm=llm, sms_sender=sms)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        await login(client, "9876500001")
        url = await _consented_web_chat(client)
        statuses = [(await client.post(url, json={"message": "hi"})).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]
    assert len(llm.calls) == 4  # two turns of two LLM calls; the third never reached the LLM


async def test_global_daily_cap(sessionmaker, llm, sms, login):
    import httpx

    settings = Settings(_env_file=None, environment="test", cookie_secure=False, chat_global_limit_per_day=1)
    app = create_app(settings, sessionmaker=sessionmaker, llm=llm, sms_sender=sms)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as one:
        await login(one, "9876500001")
        assert (await one.post(await _consented_web_chat(one), json={"message": "hi"})).status_code == 200
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as two:
        await login(two, "9876500002")
        blocked = await two.post(await _consented_web_chat(two), json={"message": "hi"})
    assert blocked.status_code == 429 and "busy" in blocked.json()["message"]


def wa(text=None, reply_id=None, sender="919876500001"):
    return IncomingMessage("m", sender, "interactive" if reply_id else "text", text, reply_id=reply_id)


async def test_whatsapp_is_rate_limited_before_the_agent(strict_settings, sessionmaker, llm, sms):
    handler = create_app(strict_settings, sessionmaker=sessionmaker, llm=llm, sms_sender=sms).state.whatsapp_handler
    await handler(wa("hi"))
    await handler(wa("yes"))
    replies = [await handler(wa("I am a farmer")) for _ in range(3)]
    assert replies[:2] == ["REPLY", "REPLY"] and replies[2] == RATE_LIMITED


# --- WhatsApp consent and de-duplication ---------------------------------------------------------


async def test_yes_before_the_notice_is_not_consent(app):
    handler = app.state.whatsapp_handler
    assert await handler(wa("yes")) == CONSENT_NOTICE  # a first-message "yes" never saw the notice
    assert await handler(wa("yes")) == WELCOME


class ButtonClient:
    def __init__(self):
        self.buttons = []

    async def send_buttons(self, to, body, buttons):
        self.buttons.append((to, body, tuple(buttons)))


async def test_consent_with_buttons(settings, sessionmaker, llm, sms):
    client = ButtonClient()
    app = create_app(settings, sessionmaker=sessionmaker, llm=llm, sms_sender=sms, whatsapp_client=client)
    handler = app.state.whatsapp_handler

    assert await handler(wa("hi")) is None  # the notice went out with buttons
    [(to, body, buttons)] = client.buttons
    assert to == "919876500001" and body == CONSENT_NOTICE and buttons == CONSENT_BUTTONS
    assert len(body) <= 1024 and all(len(title) <= 20 for _, title in buttons)

    assert await handler(wa("No / नहीं", reply_id=CONSENT_NO)) == CONSENT_DECLINED
    assert await handler(wa("I agree / सहमत", reply_id=CONSENT_YES)) == WELCOME
    assert await handler(wa("I am 45")) == "REPLY"


async def test_claim_message_once_across_workers(sessionmaker):
    assert await claim_message(sessionmaker, "wamid.1")
    assert not await claim_message(sessionmaker, "wamid.1")
    assert await claim_message(sessionmaker, "wamid.2")


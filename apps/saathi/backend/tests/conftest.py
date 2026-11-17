"""API test fixtures: in-memory SQLite, fake LLM, captured SMS."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

import httpx
import pytest
from agents_core.llm.testing import ScriptedLLM
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from saathi.app import create_app
from saathi.config import Settings
from saathi.db import Base, Role, User, create_sessionmaker
from saathi.services.schemes import seed_schemes


class CapturedSms:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, phone_e164: str, text: str) -> None:
        self.sent.append((phone_e164, text))

    def last_code(self) -> str:
        return re.match(r"(\d{6})", self.sent[-1][1]).group(1)


@pytest.fixture(autouse=True)
def _no_real_speech(monkeypatch):
    monkeypatch.setenv("SPEECH_PROVIDER", "none")  # a developer's .env must not reach real services


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, environment="test", cookie_secure=False, admin_emails="boss@example.org")


@pytest.fixture
async def sessionmaker(settings: Settings):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # SQLite needs this for ON DELETE CASCADE
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_sessionmaker(engine)
    async with factory() as db:
        await seed_schemes(db, settings.schemes_dir)
    yield factory
    await engine.dispose()


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def sms() -> CapturedSms:
    return CapturedSms()


@pytest.fixture
def app(settings, sessionmaker, llm, sms):
    return create_app(settings, sessionmaker=sessionmaker, llm=llm, sms_sender=sms)


@pytest.fixture
def make_client(app):
    clients: list[httpx.AsyncClient] = []

    def factory() -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    yield factory


@pytest.fixture
def login(sms, sessionmaker):
    async def do_login(client: httpx.AsyncClient, phone: str, role: Role = Role.CITIZEN) -> dict:
        csrf = (await client.get("/api/auth/csrf")).json()["csrf_token"]
        client.headers["x-csrf-token"] = csrf
        assert (await client.post("/api/auth/otp/request", json={"phone": phone})).status_code == 202
        response = await client.post("/api/auth/otp/verify", json={"phone": phone, "code": sms.last_code()})
        assert response.status_code == 200, response.text
        user = response.json()
        if role is not Role.CITIZEN:
            async with sessionmaker() as db:
                await db.execute(update(User).where(User.phone_e164 == f"+91{phone[-10:]}").values(role=role))
                await db.commit()
        return user

    return do_login


@pytest.fixture
async def citizen_client(make_client, login) -> AsyncIterator[httpx.AsyncClient]:
    client = make_client()
    await login(client, "9876500001")
    yield client

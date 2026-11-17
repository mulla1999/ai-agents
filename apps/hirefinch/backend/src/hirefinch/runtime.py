"""Long-lived dependencies (``Runtime``) and the per-user view of them (``UserRuntime``).

Every request and every scheduled job works through a ``UserRuntime``: it carries the user's id and
that user's own email sender, LLM and submission routes, built from their encrypted settings. No
user ever sends through another user's (or the server's) credentials.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx
from agents_core.llm import LLMProvider
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .db import paths
from .applications.routes import EmailRoute, ManualRoute, MockATS, Route
from .config import Settings
from .connectors.catalog import API_HOSTS
from .db import create_engine, create_sessionmaker
from .net import SafeFetcher
from .notifications.email import EmailSender, FileMailbox
from .security.crypto import SecretBox
from .security.ratelimit import MemoryLimiter, RedisLimiter, build_limiter

log = logging.getLogger(__name__)


@dataclass
class UserRuntime:
    user_id: int
    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    http: httpx.AsyncClient
    fetcher: SafeFetcher
    sender: EmailSender
    routes: dict[str, Route]
    llm: LLMProvider | None
    llm_error: str | None = None
    llm_verified: bool = False
    credentials: dict[str, dict] = field(default_factory=dict)  # per-source keys, decrypted in memory only


@dataclass
class Runtime:
    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    http: httpx.AsyncClient
    fetcher: SafeFetcher
    box: SecretBox
    # Test doubles: when set, every user gets these instead of their own settings.
    sender_override: EmailSender | None = None
    llm_override: LLMProvider | None = None
    limiter: MemoryLimiter | RedisLimiter = field(default_factory=MemoryLimiter)
    _verified: set[int] = field(default_factory=set)

    async def for_user(self, db: AsyncSession, user_id: int) -> UserRuntime:
        from .services import integrations  # local: services import the runtime type

        if self.sender_override is not None:
            sender = self.sender_override
        else:
            row = await integrations.get_row(db, user_id, "email")
            if row is None and self.settings.environment != "production":
                # Local development: a per-user file mailbox stands in, and nothing is sent.
                sender = FileMailbox("hirefinch@localhost", self.settings.data_dir / "mailbox" / str(user_id))
            else:
                sender = integrations.build_sender(self.settings, self.http, self.box, row)
        if self.llm_override is not None:
            llm, llm_error = self.llm_override, None
        else:
            llm, llm_error = integrations.build_llm(self.settings, self.box, await integrations.get_row(db, user_id, "llm"))
        routes: dict[str, Route] = {"manual": ManualRoute(), "email": EmailRoute(sender)}
        if self.settings.mock_enabled:
            routes["mock"] = MockATS(self.settings.data_dir / "mock_ats" / f"{user_id}.json")
        credentials: dict[str, dict] = {}
        for source_kind, integration_kind in integrations.SOURCE_CREDENTIALS.items():
            row = await integrations.get_row(db, user_id, integration_kind)
            if row is not None:
                credentials[source_kind] = {**row.config, **self.box.open(row.secret)}
        return UserRuntime(user_id, self.settings, self.sessionmaker, self.http, self.fetcher, sender, routes, llm,
                           llm_error, llm_verified=user_id in self._verified, credentials=credentials)

    def mark_llm_verified(self, user_id: int, ok: bool) -> None:
        (self._verified.add if ok else self._verified.discard)(user_id)

    async def close(self) -> None:
        await self.http.aclose()


def build_runtime(
    settings: Settings,
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    sender: EmailSender | None = None,
    llm: LLMProvider | None = None,
    fetcher: SafeFetcher | None = None,
    http: httpx.AsyncClient | None = None,
) -> Runtime:
    settings.ensure_dirs()
    paths.configure(settings.data_dir, settings.artifacts_dir)  # stored file locations resolve against these
    if sessionmaker is None:
        sessionmaker = create_sessionmaker(create_engine(settings.db_url))
    http = http or httpx.AsyncClient(timeout=settings.http_timeout_seconds)
    fetcher = fetcher or SafeFetcher(http, allowed_hosts=API_HOSTS | settings.allowed_hosts,
                                     user_agent=settings.http_user_agent,
                                     min_interval=settings.http_min_interval_seconds)
    limiter = build_limiter(settings.redis_url.get_secret_value() if settings.redis_url else None)
    return Runtime(settings, sessionmaker, http, fetcher, SecretBox.from_settings(settings), sender, llm, limiter)

"""HireFinch settings, read from ``HIREFINCH_*`` environment variables or the workspace ``.env``.

Only server infrastructure lives here. Each user's profile, preferences, policy and connections
(SMTP, LLM keys) are stored per account in the database, secrets encrypted, and edited in the UI.
The email/LLM/Adzuna variables below are read only by ``hirefinch import-env-integrations``, which
copies them into the superadmin's encrypted settings once.
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from agents_core.llm import LLMSettings
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The product name shown to users (web app, emails, authenticator). Change it here to rebrand.
BRAND = "HireFinch"

APP_ROOT = Path(__file__).resolve().parents[3]  # apps/hirefinch


class Settings(BaseSettings):
    # The workspace .env, wherever a command runs from (the migration step runs inside backend/).
    model_config = SettingsConfigDict(env_prefix="HIREFINCH_", env_file=(str(APP_ROOT.parents[1] / ".env"), ".env"),
                                      extra="ignore", env_ignore_empty=True)

    environment: Literal["development", "production", "test"] = "development"
    public_url: str = "http://localhost:5173"
    # Keys HMACs for tokens and signed values. Required in production; random per process otherwise.
    secret_key: SecretStr | None = None
    # Fernet keys (comma-separated, newest first) that encrypt users' stored secrets. Required in
    # production; generated into data_dir/.encryption_key for local development.
    encryption_keys: SecretStr | None = None
    # This account becomes superadmin when it registers (or via `hirefinch create-superadmin`).
    superadmin_email: str | None = None
    cookie_secure: bool = False
    login_session_hours: int = 12
    # Shared sign-in rate limits across backend instances (redis://host:6379/0). Optional: without it
    # the limits are kept per process, which is right for a single instance.
    redis_url: SecretStr | None = None
    # Development only: allow SMTP hosts / LLM endpoints on private addresses (e.g. a local mail catcher).
    allow_private_hosts: bool = False

    # Defaults to SQLite under data_dir; use PostgreSQL in production.
    database_url: SecretStr | None = None
    data_dir: Path = APP_ROOT / "data"  # private: database, master resumes, local mailbox
    artifacts_dir: Path = APP_ROOT / "artifacts"  # generated resumes and application records
    # Comma-separated folders the "find my resume" helper may list (file names only, PDF/DOCX).
    resume_search_paths: str = ""

    llm_provider: str | None = None
    # Overrides the shared LLM_TEMPERATURE for this agent. "none" sends no temperature at all,
    # which reasoning models such as GPT-5.x require.
    llm_temperature: str | None = None
    # Background scheduler (discovery, outbox, digest). Off in tests.
    scheduler_enabled: bool = True
    scheduler_tick_seconds: int = 30

    # Email: "file" writes .eml files to data_dir/mailbox and sends nothing; "smtp" and "gmail_api"
    # deliver for real and are used only after you configure them.
    email_provider: Literal["file", "smtp", "gmail_api"] = "file"
    email_from: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    gmail_client_id: str | None = None
    gmail_client_secret: SecretStr | None = None
    gmail_refresh_token: SecretStr | None = None

    # Job sources that need keys.
    adzuna_app_id: str | None = None
    adzuna_app_key: SecretStr | None = None

    # Outbound HTTP: extra hosts the fetcher may contact (career pages), comma-separated.
    http_allowed_hosts: str = ""
    http_timeout_seconds: float = 20.0
    http_min_interval_seconds: float = 2.0
    http_user_agent: str = "hirefinch/0.1 (personal job search; respects robots.txt)"

    @model_validator(mode="after")
    def _production_safety(self) -> Settings:
        if self.secret_key is None and self.environment != "production":
            self.secret_key = SecretStr(secrets.token_urlsafe(48))
        if self.environment == "production":
            if self.secret_key is None or len(self.secret_key.get_secret_value()) < 32:
                raise ValueError("HIREFINCH_SECRET_KEY must be a random value of 32+ characters in production")
            if self.encryption_keys is None:
                raise ValueError("HIREFINCH_ENCRYPTION_KEYS is required in production (see the README)")
            if self.allow_private_hosts:
                raise ValueError("HIREFINCH_ALLOW_PRIVATE_HOSTS must be false in production")
            if not self.public_url.startswith("https://"):
                raise ValueError("HIREFINCH_PUBLIC_URL must be an https:// URL in production")
            if not self.cookie_secure:
                raise ValueError("HIREFINCH_COOKIE_SECURE must be true in production")
        return self

    def llm_settings(self) -> LLMSettings:
        update: dict[str, object] = {}
        if self.llm_provider:
            update["llm_provider"] = self.llm_provider
        if self.llm_temperature is not None:
            value = self.llm_temperature.strip().lower()
            update["llm_temperature"] = None if value in ("none", "default", "") else float(value)
        shared = LLMSettings()
        return shared.model_copy(update=update) if update else shared

    @property
    def secret(self) -> str:
        assert self.secret_key is not None  # set by _production_safety
        return self.secret_key.get_secret_value()

    @property
    def mock_enabled(self) -> bool:
        """The demo job source and simulated ATS exist only outside production."""
        return self.environment != "production"

    @property
    def db_url(self) -> str:
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        return f"sqlite+aiosqlite:///{self.data_dir / 'hirefinch.db'}"

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return frozenset(h.strip().lower() for h in self.http_allowed_hosts.split(",") if h.strip())

    @property
    def resume_search_dirs(self) -> list[Path]:
        return [Path(p.strip()).expanduser() for p in self.resume_search_paths.split(",") if p.strip()]

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.data_dir / "masters", self.data_dir / "mailbox", self.artifacts_dir):
            path.mkdir(parents=True, exist_ok=True)
        for sub in ("resumes", "job_descriptions", "application_records", "reports"):
            (self.artifacts_dir / sub).mkdir(exist_ok=True)


LEGACY_ENV_PREFIX = "JOB_AGENT_"  # the name before the HireFinch rename; still honoured so old deployments keep working


@lru_cache
def get_settings() -> Settings:
    for key, value in list(os.environ.items()):
        if key.startswith(LEGACY_ENV_PREFIX):
            os.environ.setdefault("HIREFINCH_" + key.removeprefix(LEGACY_ENV_PREFIX), value)
    return Settings()

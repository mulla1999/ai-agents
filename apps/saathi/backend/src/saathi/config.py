"""Saathi settings, read from ``SAATHI_*`` environment variables or the workspace ``.env``.

LLM credentials are shared across agents (see ``agents_core.llm.LLMSettings``);
``SAATHI_LLM_PROVIDER`` lets Saathi use a different provider from the workspace default.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from agents_core.llm import LLMSettings
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_SCHEMES_DIR = Path(__file__).resolve().parents[2] / "data" / "schemes"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SAATHI_", env_file=".env", extra="ignore", env_ignore_empty=True)

    environment: Literal["development", "production", "test"] = "development"
    # Public base URL of the site (what the browser sees), used for OAuth redirects.
    public_url: str = "http://localhost:8080"
    # Signs OAuth state cookies and keys the OTP hashes. Required in production; outside production a
    # random per-process key is generated when unset (sign-ins in progress do not survive a restart).
    secret_key: SecretStr | None = None

    # e.g. postgresql+asyncpg://user:password@host:5432/saathi — always from the environment.
    database_url: SecretStr | None = None

    llm_provider: str | None = None
    schemes_dir: Path = _DEFAULT_SCHEMES_DIR
    include_draft_schemes: bool = True
    max_questions: int = 10
    session_ttl_seconds: int = 24 * 60 * 60

    # Web sign-in
    login_session_days: int = 7
    cookie_secure: bool = True
    admin_emails: str = ""
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    sms_provider: Literal["console", "twilio"] = "console"
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from_number: str | None = None
    consent_version: str = "2026-10-v1"

    whatsapp_verify_token: SecretStr | None = None
    whatsapp_app_secret: SecretStr | None = None
    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_graph_version: str = "v21.0"
    # The bot's number in international format without "+" (e.g. 919876543210). Enables
    # "Sign in with WhatsApp" on the website, which costs nothing per sign-in.
    whatsapp_login_number: str | None = None

    @model_validator(mode="after")
    def _production_safety(self) -> Settings:
        if self.secret_key is None and self.environment != "production":
            self.secret_key = SecretStr(secrets.token_urlsafe(48))
        if self.environment == "production":
            if self.secret_key is None or len(self.secret_key.get_secret_value()) < 32:
                raise ValueError("SAATHI_SECRET_KEY must be set to a random value of 32+ characters in production")
            if self.sms_provider == "console":
                raise ValueError("SAATHI_SMS_PROVIDER=console logs OTP codes and is not allowed in production")
            if not self.cookie_secure:
                raise ValueError("SAATHI_COOKIE_SECURE must be true in production")
        return self

    def llm_settings(self) -> LLMSettings:
        shared = LLMSettings()
        return shared.model_copy(update={"llm_provider": self.llm_provider}) if self.llm_provider else shared

    @property
    def secret(self) -> str:
        assert self.secret_key is not None  # set by _production_safety
        return self.secret_key.get_secret_value()

    @property
    def admin_email_set(self) -> frozenset[str]:
        return frozenset(e.strip().lower() for e in self.admin_emails.split(",") if e.strip())

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def whatsapp_login_enabled(self) -> bool:
        return self.whatsapp_configured and bool(self.whatsapp_login_number)

    @property
    def whatsapp_configured(self) -> bool:
        return all(
            (
                self.whatsapp_verify_token,
                self.whatsapp_app_secret,
                self.whatsapp_access_token,
                self.whatsapp_phone_number_id,
            )
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Per-user connections (email, LLM, Adzuna) and superadmin platform settings.

* Secret fields are encrypted with ``SecretBox`` and never returned by the API: reads report only
  which secret fields are set. Saving a blank secret keeps the stored one.
* User-supplied hosts are checked on save *and* on use: SMTP servers and LLM endpoints must resolve
  to public addresses (no SSRF into the server's network), SMTP only on mail ports.
* A user's LLM always needs the user's own API key. Keyless modes (Azure managed identity, Vertex
  AI service accounts) are not offered, because they would run on the *server's* cloud identity.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from agents_core.llm import LLMProvider
from pydantic import BaseModel, EmailStr, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import PlatformSetting, UserIntegration, utcnow
from ..errors import ServiceError
from ..notifications.email import EmailSender, GmailApiSender, ResendSender, SmtpSender, UnconfiguredSender
from ..security.crypto import SecretBox, SecretError
from ..security.hosts import UnsafeHost, ensure_https_endpoint, ensure_public_host, ensure_smtp_target
from .audit import record

# ---------------------------------------------------------------- schemas (non-secret / secret split)


class SmtpConfig(BaseModel):
    provider: Literal["smtp"] = "smtp"
    host: str = Field(min_length=3, max_length=253)
    port: int = 587
    username: str | None = Field(default=None, max_length=320)
    from_address: EmailStr
    starttls: bool = True


class GmailConfig(BaseModel):
    provider: Literal["gmail_api"] = "gmail_api"
    client_id: str = Field(min_length=10, max_length=300)
    from_address: EmailStr


class ResendConfig(BaseModel):
    provider: Literal["resend"] = "resend"
    from_address: EmailStr  # must be on a domain verified in Resend


class LLMConfig(BaseModel):
    provider: Literal["azure_openai", "openai_compatible", "gemini"]
    endpoint: str | None = Field(default=None, max_length=500)  # azure: https://<resource>.openai.azure.com or .services.ai.azure.com
    deployment: str | None = Field(default=None, max_length=120)  # azure
    api_version: str | None = Field(default="2025-04-01-preview", max_length=40)  # azure
    base_url: str | None = Field(default=None, max_length=500)  # openai_compatible; empty = api.openai.com
    model: str | None = Field(default=None, max_length=120)  # openai_compatible / gemini
    temperature: float | None = Field(default=None, ge=0, le=2)  # None for reasoning models (GPT-5.x)

    @field_validator("deployment", "model", "api_version")
    @classmethod
    def _plain(cls, value: str | None) -> str | None:
        if value is not None and not all(c.isalnum() or c in "-._:" for c in value):
            raise ValueError("letters, digits, '-', '.', '_' and ':' only")
        return value


class AdzunaConfig(BaseModel):
    app_id: str = Field(min_length=3, max_length=100)


class KeyOnlyConfig(BaseModel):
    """Sources whose only setting is the (secret) API key."""


class WebSearchConfig(BaseModel):
    """A licensed web search API the assistant uses to find postings (search engines are never scraped)."""

    provider: Literal["brave", "tavily"]


class ImapConfig(BaseModel):
    host: str = Field(min_length=3, max_length=253)  # e.g. imap.gmail.com
    port: int = 993
    username: str = Field(min_length=3, max_length=320)
    folder: str = Field(default="INBOX", max_length=100)


SECRET_FIELDS = {
    "smtp": ("password",),
    "gmail_api": ("client_secret", "refresh_token"),
    "resend": ("api_key",),
    "llm": ("api_key",),
    "adzuna": ("app_key",),
    "jooble": ("api_key",),
    "imap": ("password",),
    "websearch": ("api_key",),
    "system_email": ("password",),
    "google_oauth": ("client_secret",),
}
KINDS = ("email", "llm", "adzuna", "jooble", "imap", "websearch")
# Which integration holds the credentials for a job source (and for the assistant's web search).
SOURCE_CREDENTIALS = {"adzuna": "adzuna", "jooble": "jooble", "job_alerts": "imap", "websearch": "websearch"}


def _secret_kind(kind: str, config: dict[str, Any]) -> str:
    return config.get("provider", "smtp") if kind in ("email",) else kind


def validate_config(kind: str, config: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Validate and normalise non-secret fields; check hosts. Raises ServiceError (422)."""
    try:
        if kind in ("email", "system_email"):
            model: BaseModel = {"gmail_api": GmailConfig, "resend": ResendConfig}.get(
                config.get("provider"), SmtpConfig).model_validate(config)
            if isinstance(model, SmtpConfig):
                ensure_smtp_target(model.host, model.port, allow_private=settings.allow_private_hosts)
        elif kind == "llm":
            model = LLMConfig.model_validate(config)
            if model.provider == "azure_openai":
                if not (model.endpoint and model.deployment and model.api_version):
                    raise ServiceError("invalid_config", "Azure OpenAI needs an endpoint, a deployment and an API version", 422)
                model.endpoint = ensure_https_endpoint(model.endpoint, allow_private=settings.allow_private_hosts)
            elif model.provider == "openai_compatible":
                if not model.model:
                    raise ServiceError("invalid_config", "enter the model name", 422)
                if model.base_url:
                    model.base_url = ensure_https_endpoint(model.base_url, allow_private=settings.allow_private_hosts)
            elif not model.model:
                raise ServiceError("invalid_config", "enter the Gemini model name, e.g. gemini-3.5-flash", 422)
        elif kind == "adzuna":
            model = AdzunaConfig.model_validate(config)
        elif kind == "jooble":
            model = KeyOnlyConfig.model_validate(config)
        elif kind == "websearch":
            model = WebSearchConfig.model_validate(config)
        elif kind == "imap":
            model = ImapConfig.model_validate(config)
            if model.port != 993:
                raise ServiceError("invalid_config", "only IMAP over TLS on port 993 is supported", 422)
            ensure_public_host(model.host, allow_private=settings.allow_private_hosts)
        else:
            raise ServiceError("invalid_kind", f"unknown integration '{kind}'", 422)
    except ValidationError as exc:
        raise ServiceError("invalid_config", "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()),
                           422) from exc
    except UnsafeHost as exc:
        raise ServiceError("unsafe_host", str(exc), 422) from exc
    return model.model_dump(mode="json")


# ---------------------------------------------------------------- storage


def public_view(row: UserIntegration | PlatformSetting | None, kind: str, box: SecretBox) -> dict[str, Any]:
    if row is None:
        return {"kind": kind, "configured": False, "config": {}, "secrets_set": []}
    try:
        secrets = box.open(row.secret)
        broken = None
    except SecretError as exc:
        secrets, broken = {}, str(exc)
    return {"kind": kind, "configured": True, "config": row.config,
            "secrets_set": sorted(k for k, v in secrets.items() if v),
            "verified_at": getattr(row, "verified_at", None) and row.verified_at.isoformat(),  # type: ignore[union-attr]
            "error": broken}


async def get_row(db: AsyncSession, user_id: int, kind: str) -> UserIntegration | None:
    return await db.scalar(select(UserIntegration).where(UserIntegration.user_id == user_id, UserIntegration.kind == kind))


async def save(db: AsyncSession, settings: Settings, box: SecretBox, user_id: int, kind: str,
               config: dict[str, Any], secrets: dict[str, str | None]) -> UserIntegration:
    if kind not in KINDS:
        raise ServiceError("invalid_kind", f"unknown integration '{kind}'", 422)
    clean = validate_config(kind, config, settings)
    row = await get_row(db, user_id, kind)
    stored = box.open(row.secret) if row is not None and row.secret else {}
    allowed = SECRET_FIELDS[_secret_kind(kind, clean)]
    for field_name in allowed:
        value = (secrets.get(field_name) or "").strip()
        if value:
            if len(value) > 4096:
                raise ServiceError("invalid_secret", f"{field_name} is too long", 422)
            stored[field_name] = value  # blank keeps what is stored
    stored = {k: v for k, v in stored.items() if k in allowed}
    required = list(allowed)
    if kind == "email" and clean.get("provider") == "smtp":
        required = ["password"] if clean.get("username") else []  # some relays accept mail without a login
    if missing := [f for f in required if not stored.get(f)]:
        raise ServiceError("missing_secret", "enter: " + ", ".join(missing), 422)
    if row is None:
        row = UserIntegration(user_id=user_id, kind=kind)
        db.add(row)
    row.config, row.secret, row.verified_at = clean, box.seal(stored), None
    await record(db, user_id, "integration.saved", f"{kind} settings saved", actor="user",
                 details={"provider": clean.get("provider"), "secrets_updated": [f for f in allowed if secrets.get(f)]})
    return row


async def delete(db: AsyncSession, user_id: int, kind: str) -> None:
    row = await get_row(db, user_id, kind)
    if row is not None:
        await db.delete(row)
        await record(db, user_id, "integration.deleted", f"{kind} settings removed", actor="user")


# ---------------------------------------------------------------- builders


def build_sender(settings: Settings, http: httpx.AsyncClient, box: SecretBox, row: UserIntegration | PlatformSetting | None,
                 *, purpose: str = "your email") -> EmailSender:
    if row is None:
        return UnconfiguredSender(f"set up {purpose} in Settings → Integrations")
    config, secrets = row.config, box.open(row.secret)
    if config.get("provider") == "resend":
        return ResendSender(config["from_address"], http, secrets.get("api_key", ""))
    if config.get("provider") == "gmail_api":
        return GmailApiSender(config["from_address"], http, config["client_id"], secrets.get("client_secret", ""),
                              secrets.get("refresh_token", ""))
    try:  # re-check at use: DNS can change after saving
        ensure_smtp_target(config["host"], int(config["port"]), allow_private=settings.allow_private_hosts)
    except UnsafeHost as exc:
        return UnconfiguredSender(str(exc))
    return SmtpSender(config["from_address"], config["host"], int(config["port"]), config.get("username"),
                      secrets.get("password"), bool(config.get("starttls", True)))


def build_llm(settings: Settings, box: SecretBox, row: UserIntegration | None) -> tuple[LLMProvider | None, str | None]:
    if row is None:
        return None, "no AI provider set up (Settings → Integrations)"
    config, key = row.config, box.open(row.secret).get("api_key")
    if not key:
        return None, "the AI provider has no API key"
    try:
        provider = config["provider"]
        if provider == "azure_openai":
            from agents_core.llm.azure_openai import AzureOpenAIProvider

            endpoint = ensure_https_endpoint(config["endpoint"], allow_private=settings.allow_private_hosts)
            return AzureOpenAIProvider(endpoint=endpoint, deployment=config["deployment"], api_version=config["api_version"],
                                       temperature=config.get("temperature"), api_key=key), None
        if provider == "openai_compatible":
            from agents_core.llm.openai_compatible import OpenAIChatProvider

            base = config.get("base_url")
            if base:
                base = ensure_https_endpoint(base, allow_private=settings.allow_private_hosts)
            return OpenAIChatProvider(model=config["model"], temperature=config.get("temperature"), api_key=key,
                                      base_url=base), None
        if provider == "gemini":
            from agents_core.llm.gemini import GeminiProvider

            return GeminiProvider(model=config["model"], temperature=config.get("temperature"), api_key=key), None
    except (UnsafeHost, KeyError, ImportError) as exc:
        return None, f"AI provider unavailable: {exc}"
    except Exception as exc:  # provider SDKs raise their own types on bad settings
        return None, f"AI provider unavailable: {exc.__class__.__name__}"
    return None, f"unknown provider {config.get('provider')!r}"


async def mark_verified(db: AsyncSession, user_id: int, kind: str) -> None:
    row = await get_row(db, user_id, kind)
    if row is not None:
        row.verified_at = utcnow()


# ---------------------------------------------------------------- platform settings (superadmin)

PLATFORM_DEFAULTS: dict[str, dict[str, Any]] = {
    "registration": {"open": True, "allowed_domains": [], "verify_email": True},
    "retention": {"inactive_days": 365, "warn_days": 30, "audit_days": 365, "notification_days": 180},
    "google_oauth": {"client_id": ""},
    "limits": {"max_resumes": 5, "max_boards_per_source": 100, "max_career_pages": 25, "min_discovery_minutes": 60,
               "daily_outreach_cap": 10, "daily_application_cap": 20},
}


async def platform_get(db: AsyncSession, key: str) -> PlatformSetting | None:
    return await db.scalar(select(PlatformSetting).where(PlatformSetting.key == key))


async def platform_config(db: AsyncSession, key: str) -> dict[str, Any]:
    row = await platform_get(db, key)
    return {**PLATFORM_DEFAULTS.get(key, {}), **(row.config if row else {})}


async def platform_save(db: AsyncSession, settings: Settings, box: SecretBox, key: str, config: dict[str, Any],
                        secrets: dict[str, str | None], actor_id: int) -> PlatformSetting:
    if key == "system_email":
        clean = validate_config("system_email", config, settings)
    elif key == "registration":
        domains = [str(d).strip().lower().lstrip("@") for d in config.get("allowed_domains") or [] if str(d).strip()]
        clean = {"open": bool(config.get("open", True)), "allowed_domains": domains[:50],
                 "verify_email": bool(config.get("verify_email", True))}
    elif key == "limits":
        base = PLATFORM_DEFAULTS["limits"]
        clean = {k: max(1, min(int(config.get(k, v)), 10000)) for k, v in base.items()}
    elif key == "retention":
        base = PLATFORM_DEFAULTS["retention"]
        clean = {k: max(0, min(int(config.get(k, v)), 3650)) for k, v in base.items()}
        if clean["inactive_days"] and clean["inactive_days"] < 90:
            raise ServiceError("invalid_config", "inactive accounts must be kept at least 90 days (or 0 to keep them)", 422)
        clean["warn_days"] = max(clean["warn_days"], 7)
        clean["audit_days"], clean["notification_days"] = max(clean["audit_days"], 30), max(clean["notification_days"], 30)
    elif key == "google_oauth":
        client_id = str(config.get("client_id") or "").strip()
        if client_id and not client_id.endswith(".apps.googleusercontent.com"):
            raise ServiceError("invalid_config", "the client id ends with .apps.googleusercontent.com", 422)
        clean = {"client_id": client_id}
    else:
        raise ServiceError("invalid_key", f"unknown platform setting '{key}'", 422)
    row = await platform_get(db, key)
    stored = box.open(row.secret) if row is not None and row.secret else {}
    for field_name in SECRET_FIELDS.get(key if key != "system_email" else _secret_kind("email", clean), ()):
        if (value := (secrets.get(field_name) or "").strip()):
            stored[field_name] = value
    if row is None:
        row = PlatformSetting(key=key)
        db.add(row)
    row.config, row.secret = clean, (box.seal(stored) if stored else None)
    await record(db, actor_id, "platform.settings", f"platform setting '{key}' updated", actor="user")
    return row


async def system_sender(db: AsyncSession, settings: Settings, http: httpx.AsyncClient, box: SecretBox) -> EmailSender:
    return build_sender(settings, http, box, await platform_get(db, "system_email"), purpose="the platform email")

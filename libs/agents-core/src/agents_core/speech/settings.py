"""Speech settings shared by every agent, from unprefixed environment variables (``SPEECH_PROVIDER``, ...)."""

from __future__ import annotations

import json

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .base import SpeechError, SpeechProvider


class SpeechSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # none | azure | bhashini  ("bhashini" also covers a self-hosted AI4Bharat Dhruva server)
    speech_provider: str = "none"
    speech_default_language: str = "hi"
    speech_voice_replies: bool = True

    azure_speech_key: SecretStr | None = None
    azure_speech_region: str | None = None
    azure_speech_voices: str | None = None  # JSON, e.g. {"hi": "hi-IN-MadhurNeural"}

    bhashini_user_id: str | None = None
    bhashini_ulca_api_key: SecretStr | None = None
    bhashini_pipeline_id: str | None = None
    bhashini_inference_url: str | None = None
    bhashini_inference_api_key: SecretStr | None = None
    bhashini_service_ids: str | None = None  # JSON, e.g. {"asr:hi": "ai4bharat/conformer-hi-gpu--t4"}


def _json(value: str | None, name: str) -> dict[str, str]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SpeechError(f"{name} must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise SpeechError(f"{name} must be a JSON object")
    return {str(k): str(v) for k, v in parsed.items()}


def create_speech(settings: SpeechSettings, http: httpx.AsyncClient) -> SpeechProvider | None:
    """The configured provider, or None when speech is switched off."""
    provider = settings.speech_provider.lower()
    if provider == "none":
        return None
    if provider == "azure":
        from .azure import AzureSpeechProvider

        if not (settings.azure_speech_key and settings.azure_speech_region):
            raise SpeechError("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION are required for SPEECH_PROVIDER=azure")
        return AzureSpeechProvider(
            key=settings.azure_speech_key.get_secret_value(),
            region=settings.azure_speech_region,
            http=http,
            voices=_json(settings.azure_speech_voices, "AZURE_SPEECH_VOICES"),
        )
    if provider == "bhashini":
        from .bhashini import DEFAULT_PIPELINE_ID, BhashiniSpeechProvider

        return BhashiniSpeechProvider(
            http=http,
            user_id=settings.bhashini_user_id,
            ulca_api_key=settings.bhashini_ulca_api_key.get_secret_value() if settings.bhashini_ulca_api_key else None,
            pipeline_id=settings.bhashini_pipeline_id or DEFAULT_PIPELINE_ID,
            inference_url=settings.bhashini_inference_url,
            inference_api_key=(
                settings.bhashini_inference_api_key.get_secret_value() if settings.bhashini_inference_api_key else None
            ),
            service_ids=_json(settings.bhashini_service_ids, "BHASHINI_SERVICE_IDS"),
        )
    raise SpeechError(f"unknown SPEECH_PROVIDER {settings.speech_provider!r}; use none, azure or bhashini")

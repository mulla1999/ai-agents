"""LLM settings shared by every agent in the workspace.

Read from standard, unprefixed environment variables (``LLM_PROVIDER``, ``AZURE_OPENAI_ENDPOINT``,
``GEMINI_API_KEY``, ...) so one ``.env`` configures all agents. An agent can still pick a different
provider for itself with ``model_copy(update={"llm_provider": ...})``.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True, env_parse_none_str="none"
    )

    llm_provider: str = "azure_openai"
    llm_temperature: float | None = 0.2

    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_api_key: SecretStr | None = None

    gemini_model: str = "gemini-2.5-flash"
    gemini_api_key: SecretStr | None = None
    gemini_use_vertex: bool = False
    gemini_project: str | None = None
    gemini_location: str = "asia-south1"

    openai_base_url: str | None = None
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None

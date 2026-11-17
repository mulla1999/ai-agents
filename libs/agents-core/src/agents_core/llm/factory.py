"""Builds the configured LLM provider. Add a backend by registering a builder with ``register_provider``."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import SecretStr

from .settings import LLMSettings
from .base import LLMProvider

ProviderBuilder = Callable[[LLMSettings], LLMProvider]

_REGISTRY: dict[str, ProviderBuilder] = {}


class ConfigError(ValueError):
    """Settings are missing or inconsistent."""


def register_provider(name: str) -> Callable[[ProviderBuilder], ProviderBuilder]:
    def decorator(builder: ProviderBuilder) -> ProviderBuilder:
        _REGISTRY[name] = builder
        return builder

    return decorator


def available_providers() -> list[str]:
    return sorted(_REGISTRY)


def create_llm(settings: LLMSettings) -> LLMProvider:
    try:
        builder = _REGISTRY[settings.llm_provider]
    except KeyError:
        raise ConfigError(
            f"unknown LLM provider {settings.llm_provider!r}; choose one of {available_providers()}"
        ) from None
    return builder(settings)


def _value(settings: LLMSettings, attr: str, *, required: bool = True) -> str | None:
    value = getattr(settings, attr)
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    if required and not value:
        raise ConfigError(f"{attr.upper()} is required for provider {settings.llm_provider!r}")
    return value or None


@register_provider("azure_openai")
def _azure_openai(settings: LLMSettings) -> LLMProvider:
    from .azure_openai import AzureOpenAIProvider

    return AzureOpenAIProvider(
        endpoint=_value(settings, "azure_openai_endpoint"),
        deployment=_value(settings, "azure_openai_deployment"),
        api_version=settings.azure_openai_api_version,
        api_key=_value(settings, "azure_openai_api_key", required=False),
        temperature=settings.llm_temperature,
    )


@register_provider("gemini")
def _gemini(settings: LLMSettings) -> LLMProvider:
    from .gemini import GeminiProvider

    if settings.gemini_use_vertex:
        return GeminiProvider(
            model=settings.gemini_model,
            temperature=settings.llm_temperature,
            vertex_project=_value(settings, "gemini_project"),
            vertex_location=settings.gemini_location,
        )
    return GeminiProvider(
        model=settings.gemini_model,
        temperature=settings.llm_temperature,
        api_key=_value(settings, "gemini_api_key"),
    )


@register_provider("openai_compatible")
def _openai_compatible(settings: LLMSettings) -> LLMProvider:
    from .openai_compatible import OpenAIChatProvider

    return OpenAIChatProvider(
        model=_value(settings, "openai_model"),
        temperature=settings.llm_temperature,
        # Local servers such as Ollama ignore the key but the client requires one.
        api_key=_value(settings, "openai_api_key", required=False) or "not-needed",
        base_url=_value(settings, "openai_base_url", required=False),
    )

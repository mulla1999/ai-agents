import pytest

from agents_core.llm import ConfigError, LLMSettings, available_providers, create_llm
from agents_core.llm.base import LLMError, parse_json_object

PROVIDER_ENV = ("AZURE_OPENAI_ENDPOINT", "GEMINI_API_KEY", "OPENAI_MODEL")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in PROVIDER_ENV:
        monkeypatch.delenv(var, raising=False)


def settings(**values) -> LLMSettings:
    return LLMSettings(_env_file=None, **values)


def test_all_builtin_providers_registered():
    assert {"azure_openai", "gemini", "openai_compatible"} <= set(available_providers())


def test_unknown_provider_is_rejected():
    with pytest.raises(ConfigError, match="unknown LLM provider"):
        create_llm(settings(llm_provider="nope"))


@pytest.mark.parametrize(
    ("provider", "missing"),
    [("azure_openai", "AZURE_OPENAI_ENDPOINT"), ("gemini", "GEMINI_API_KEY"), ("openai_compatible", "OPENAI_MODEL")],
)
def test_missing_settings_are_reported_by_env_name(provider, missing):
    with pytest.raises(ConfigError, match=missing):
        create_llm(settings(llm_provider=provider))


@pytest.mark.parametrize(
    ("provider", "values", "expected"),
    [
        ("azure_openai", {"azure_openai_endpoint": "https://x.openai.azure.com", "azure_openai_deployment": "d", "azure_openai_api_key": "k"}, "AzureOpenAIProvider"),
        ("gemini", {"gemini_api_key": "k"}, "GeminiProvider"),
        ("openai_compatible", {"openai_model": "llama3", "openai_base_url": "http://localhost:11434/v1"}, "OpenAIChatProvider"),
    ],
)  # fmt: skip
def test_each_provider_builds_from_settings(provider, values, expected):
    pytest.importorskip("openai" if provider != "gemini" else "google.genai")
    assert type(create_llm(settings(llm_provider=provider, **values))).__name__ == expected


def test_parse_json_object_handles_code_fences():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(LLMError):
        parse_json_object("[1, 2]")

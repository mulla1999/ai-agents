"""Azure OpenAI provider. Authenticates with an API key, or with Microsoft Entra ID when no key is set."""

from __future__ import annotations

from .base import LLMError
from .openai_compatible import OpenAIChatProvider

_ENTRA_SCOPE = "https://cognitiveservices.azure.com/.default"


class AzureOpenAIProvider(OpenAIChatProvider):
    name = "azure_openai"

    def __init__(
        self,
        *,
        endpoint: str,
        deployment: str,
        api_version: str,
        temperature: float | None,
        api_key: str | None = None,
    ) -> None:
        try:
            from openai import AsyncAzureOpenAI
        except ImportError as exc:
            raise LLMError("install the Azure extra: pip install 'agents-core[azure]'") from exc

        if api_key:
            client = AsyncAzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)
        else:
            try:
                from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
            except ImportError as exc:
                raise LLMError("keyless auth needs azure-identity: pip install 'agents-core[azure]'") from exc
            client = AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                azure_ad_token_provider=get_bearer_token_provider(DefaultAzureCredential(), _ENTRA_SCOPE),
                api_version=api_version,
            )
        # On Azure the "model" is the name of your deployment.
        super().__init__(model=deployment, temperature=temperature, client=client)

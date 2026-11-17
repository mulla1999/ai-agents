"""Provider for any server that speaks the OpenAI Chat Completions API (OpenAI, Ollama, vLLM, ...)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .base import LLMError, LLMProvider, Message


class OpenAIChatProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(
        self,
        *,
        model: str,
        temperature: float | None,
        client: Any | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        if client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise LLMError("install the OpenAI extra: pip install 'agents-core[openai]'") from exc
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._client = client
        self._model = model
        self._temperature = temperature

    async def complete(self, messages: Sequence[Message], *, json_output: bool = False) -> str:
        kwargs: dict[str, Any] = {}
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        if json_output:
            kwargs["response_format"] = {"type": "json_object"}
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            **kwargs,
        )
        return response.choices[0].message.content or ""

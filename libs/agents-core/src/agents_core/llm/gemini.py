"""Gemini provider, via Google AI Studio (API key) or Vertex AI (application default credentials)."""

from __future__ import annotations

from collections.abc import Sequence

from .base import LLMError, LLMProvider, Message


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(
        self,
        *,
        model: str,
        temperature: float | None,
        api_key: str | None = None,
        vertex_project: str | None = None,
        vertex_location: str | None = None,
    ) -> None:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise LLMError("install the Gemini extra: pip install 'agents-core[gemini]'") from exc

        if vertex_project:
            self._client = genai.Client(vertexai=True, project=vertex_project, location=vertex_location)
        else:
            self._client = genai.Client(api_key=api_key)
        self._types = types
        self._model = model
        self._temperature = temperature

    async def complete(self, messages: Sequence[Message], *, json_output: bool = False) -> str:
        types = self._types
        system = "\n\n".join(m.content for m in messages if m.role == "system") or None
        contents = [
            types.Content(role="model" if m.role == "assistant" else "user", parts=[types.Part(text=m.content)])
            for m in messages
            if m.role != "system"
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self._temperature,
            response_mime_type="application/json" if json_output else None,
        )
        response = await self._client.aio.models.generate_content(
            model=self._model, contents=contents, config=config
        )
        return response.text or ""

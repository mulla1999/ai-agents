"""The one interface the rest of Saathi uses to talk to a language model."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

Role = Literal["system", "user", "assistant"]


class LLMError(RuntimeError):
    """The model could not be reached or returned something unusable."""


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


class LLMProvider(ABC):
    """Adapter for one LLM backend. Implementations must be safe to share across requests."""

    name: str

    @abstractmethod
    async def complete(self, messages: Sequence[Message], *, json_output: bool = False) -> str:
        """Return the model's reply. With ``json_output`` the reply must be a JSON object."""

    async def complete_json(self, messages: Sequence[Message]) -> dict[str, Any]:
        return parse_json_object(await self.complete(messages, json_output=True))


def parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError("model did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise LLMError("model returned JSON that is not an object")
    return value

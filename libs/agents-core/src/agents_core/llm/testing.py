"""A scripted fake provider so agent tests run without network access or API keys."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from .base import LLMProvider, Message


class ScriptedLLM(LLMProvider):
    """Returns queued objects for JSON calls and a fixed reply otherwise; records every call."""

    name = "scripted"

    def __init__(self, json_replies: Sequence[dict[str, Any]] = (), text_reply: str = "REPLY") -> None:
        self.json_replies = list(json_replies)
        self.text_reply = text_reply
        self.calls: list[tuple[list[Message], bool]] = []

    async def complete(self, messages: Sequence[Message], *, json_output: bool = False) -> str:
        self.calls.append((list(messages), json_output))
        if json_output:
            return json.dumps(self.json_replies.pop(0) if self.json_replies else {})
        return self.text_reply

    def text_prompts(self) -> list[str]:
        """The system prompt of every non-JSON call, in order."""
        return [msgs[0].content for msgs, is_json in self.calls if not is_json]

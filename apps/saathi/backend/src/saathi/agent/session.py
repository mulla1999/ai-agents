"""Per-user conversation state and where it is kept."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol

from agents_core.llm import Message

from ..profile import UserProfile

MAX_HISTORY_MESSAGES = 12


@dataclass
class Session:
    user_id: str
    profile: UserProfile = field(default_factory=UserProfile)
    language: str | None = None
    history: list[Message] = field(default_factory=list)
    declined_fields: set[str] = field(default_factory=set)
    questions_asked: int = 0
    last_asked_field: str | None = None
    results_shown: bool = False
    updated_at: float = field(default_factory=time.monotonic)
    # Messages added since the session was loaded; persistent stores append these and clear the list.
    new_messages: list[Message] = field(default_factory=list)

    def add_turn(self, user_text: str, reply: str) -> None:
        turn = [Message("user", user_text), Message("assistant", reply)]
        self.history += turn
        self.new_messages += turn
        del self.history[:-MAX_HISTORY_MESSAGES]

    def state(self) -> dict[str, object]:
        """Conversation progress, for persistent stores."""
        return {
            "declined_fields": sorted(self.declined_fields),
            "questions_asked": self.questions_asked,
            "last_asked_field": self.last_asked_field,
            "results_shown": self.results_shown,
        }

    def restore_state(self, state: dict[str, object]) -> None:
        self.declined_fields = set(state.get("declined_fields") or [])
        self.questions_asked = int(state.get("questions_asked") or 0)
        self.last_asked_field = state.get("last_asked_field") or None  # type: ignore[assignment]
        self.results_shown = bool(state.get("results_shown"))


class SessionStore(Protocol):
    async def get(self, user_id: str) -> Session: ...
    async def save(self, session: Session) -> None: ...
    async def delete(self, user_id: str) -> None: ...


class InMemorySessionStore:
    """Process-local store; sessions expire after ``ttl_seconds`` without activity.

    Used for WhatsApp and the CLI. The web app uses the database-backed store in ``saathi.services``.
    """

    def __init__(self, ttl_seconds: int = 24 * 60 * 60) -> None:
        self._ttl = ttl_seconds
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def get(self, user_id: str) -> Session:
        async with self._lock:
            self._evict_expired()
            return self._sessions.get(user_id) or Session(user_id)

    async def save(self, session: Session) -> None:
        session.updated_at = time.monotonic()
        session.new_messages.clear()
        async with self._lock:
            self._sessions[session.user_id] = session

    async def delete(self, user_id: str) -> None:
        async with self._lock:
            self._sessions.pop(user_id, None)

    def _evict_expired(self) -> None:
        cutoff = time.monotonic() - self._ttl
        for user_id in [uid for uid, s in self._sessions.items() if s.updated_at < cutoff]:
            del self._sessions[user_id]

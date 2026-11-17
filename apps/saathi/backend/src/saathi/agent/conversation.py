"""The turn-by-turn conversation loop.

Each turn: redact IDs -> LLM extracts profile facts -> rules engine evaluates every scheme ->
either ask the most useful next question or present/explain results -> LLM phrases the reply.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, Literal, get_args

from agents_core.llm import LLMError, LLMProvider, Message, create_llm
from agents_core.privacy import redact_pii
from pydantic import BaseModel, ValidationError, field_validator

from ..config import Settings
from ..profile import PROFILE_FIELDS, UserProfile
from ..schemes import Scheme, SchemeSource, StaticSchemeSource, evaluate_all, load_schemes, next_field_to_ask
from . import prompts
from .session import InMemorySessionStore, Session, SessionStore

log = logging.getLogger(__name__)

MAX_INPUT_CHARS = 2000
FALLBACK_REPLY = (
    "Sorry, something went wrong on our side. Please try again in a little while.\n"
    "क्षमा करें, कुछ गड़बड़ हो गई। कृपया थोड़ी देर बाद फिर से कोशिश करें।"
)

Intent = Literal["provide_info", "show_results", "question", "delete_data", "other"]


class Extraction(BaseModel):
    language: str | None = None
    updates: dict[str, Any] = {}
    unknown_fields: list[str] = []
    intent: Intent = "provide_info"

    @field_validator("intent", mode="before")
    @classmethod
    def _unknown_intent(cls, value: Any) -> Any:
        return value if value in get_args(Intent) else "other"


class Agent:
    def __init__(
        self,
        llm: LLMProvider,
        schemes: Sequence[Scheme] | SchemeSource,
        store: SessionStore,
        *,
        max_questions: int = 10,
    ) -> None:
        self._llm = llm
        self._schemes = StaticSchemeSource(schemes) if isinstance(schemes, Sequence) else schemes
        self._store = store
        self._max_questions = max_questions
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def handle(self, user_id: str, text: str) -> str:
        # One turn at a time per user, so two quick messages cannot overwrite each other's updates.
        async with self._locks[user_id]:
            try:
                return await self._handle(user_id, text)
            except Exception:
                log.exception("failed to handle a message (provider=%s)", self._llm.name)
                return FALLBACK_REPLY

    async def profile(self, user_id: str) -> UserProfile:
        return (await self._store.get(user_id)).profile

    async def _handle(self, user_id: str, text: str) -> str:
        session = await self._store.get(user_id)
        first_turn = not session.history
        text = redact_pii(text.strip())[:MAX_INPUT_CHARS]

        extraction = await self._extract(session, text)
        session.language = extraction.language or session.language
        self._apply(session, extraction)

        if extraction.intent == "delete_data":
            reply = await self._respond(session, text, prompts.DELETE_TASK)
            await self._store.delete(user_id)
            return reply

        matches = evaluate_all(await self._schemes.active(), session.profile)
        next_field = None
        if extraction.intent not in ("show_results", "question") and session.questions_asked < self._max_questions:
            next_field = next_field_to_ask(matches, skip=session.declined_fields)

        if next_field:
            task = prompts.ask_task(next_field, first_turn=first_turn)
            session.questions_asked += 1
        else:
            task = prompts.answer_task(matches, results_already_shown=session.results_shown)
            session.results_shown = True
        session.last_asked_field = next_field

        reply = await self._respond(session, text, task)
        session.add_turn(text, reply)
        await self._store.save(session)
        return reply

    async def _extract(self, session: Session, text: str) -> Extraction:
        messages = [
            Message("system", prompts.extraction_system(session.last_asked_field)),
            *session.history[-4:],
            Message("user", text),
        ]
        try:
            return Extraction.model_validate(await self._llm.complete_json(messages))
        except (LLMError, ValidationError):
            log.warning("could not parse extraction output (provider=%s)", self._llm.name)
            return Extraction()

    @staticmethod
    def _apply(session: Session, extraction: Extraction) -> None:
        for name, value in extraction.updates.items():
            if name not in PROFILE_FIELDS or value is None:
                continue
            try:
                setattr(session.profile, name, value)
            except ValidationError:
                log.info("ignored invalid value for profile field %s", name)
        for name in extraction.unknown_fields:
            if name in PROFILE_FIELDS and getattr(session.profile, name) is None:
                session.declined_fields.add(name)

    async def _respond(self, session: Session, text: str, task: str) -> str:
        messages = [
            Message("system", f"{prompts.persona(session.language)}\n{task}"),
            *session.history,
            Message("user", text),
        ]
        reply = (await self._llm.complete(messages)).strip()
        return reply or FALLBACK_REPLY


def build_agent(
    settings: Settings,
    *,
    llm: LLMProvider | None = None,
    schemes: Sequence[Scheme] | SchemeSource | None = None,
    store: SessionStore | None = None,
) -> Agent:
    return Agent(
        llm or create_llm(settings.llm_settings()),
        schemes if schemes is not None else load_schemes(settings.schemes_dir),
        store or InMemorySessionStore(ttl_seconds=settings.session_ttl_seconds),
        max_questions=settings.max_questions,
    )

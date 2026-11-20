"""HTTP server. Run with: uvicorn --factory saathi.app:create_app"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from agents_core.channels import whatsapp
from agents_core.llm import ConfigError, LLMError, LLMProvider, create_llm
from agents_core.speech import SpeechError, SpeechProvider, SpeechSettings, create_speech
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from .agent import Agent
from .api import ROUTERS
from .auth.csrf import CSRFMiddleware
from .auth.google import build_google_oauth
from .auth.sms import SmsSender, build_sms_sender
from .config import Settings, get_settings
from .db import Channel, create_engine, create_sessionmaker
from .errors import ServiceError
from .services.conversations import DbSessionStore
from .services.schemes import DbSchemeSource
from .services.whatsapp import WhatsAppCitizenHandler, claim_message

log = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    llm: LLMProvider | None = None,
    sms_sender: SmsSender | None = None,
    speech: SpeechProvider | None = None,
    whatsapp_client: whatsapp.WhatsAppClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    engine = None
    if sessionmaker is None:
        if settings.database_url is None:
            raise RuntimeError("SAATHI_DATABASE_URL is not set")
        engine = create_engine(settings.database_url.get_secret_value())
        sessionmaker = create_sessionmaker(engine)
    http = httpx.AsyncClient(timeout=20)

    if llm is None:
        try:
            llm = create_llm(settings.llm_settings())
        except (ConfigError, LLMError) as exc:
            log.warning("chat is disabled until an LLM provider is configured: %s", exc)

    scheme_source = DbSchemeSource(sessionmaker, include_drafts=settings.include_draft_schemes)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await http.aclose()
        if engine is not None:
            await engine.dispose()

    # No public API docs in production; the SPA is the only intended client.
    show_docs = settings.environment != "production"
    app = FastAPI(
        title="Saathi",
        lifespan=lifespan,
        docs_url="/api/docs" if show_docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if show_docs else None,
    )
    app.state.settings = settings
    app.state.sessionmaker = sessionmaker
    app.state.scheme_source = scheme_source
    app.state.sms_sender = sms_sender or build_sms_sender(settings, http)
    app.state.google_oauth = build_google_oauth(settings)
    app.state.web_agent = (
        Agent(llm, scheme_source, DbSessionStore(sessionmaker), max_questions=settings.max_questions) if llm else None
    )

    app.add_middleware(CSRFMiddleware)
    # Short-lived signed cookie holding only OAuth state/nonce/PKCE verifier during Google sign-in.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret,
        session_cookie="saathi_oauth",
        max_age=600,
        same_site="lax",
        https_only=settings.cookie_secure,
    )

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status_code)

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for router in ROUTERS:
        app.include_router(router)

    wa_client = whatsapp_client or (
        whatsapp.WhatsAppClient(
            access_token=settings.whatsapp_access_token.get_secret_value(),
            phone_number_id=settings.whatsapp_phone_number_id,
            graph_version=settings.whatsapp_graph_version,
            http=http,
        )
        if settings.whatsapp_configured
        else None
    )
    speech_settings = SpeechSettings()
    if speech is None:
        try:
            speech = create_speech(speech_settings, http)
        except SpeechError as exc:
            log.warning("voice notes are disabled: %s", exc)
    wa_agent = (
        Agent(llm, scheme_source, DbSessionStore(sessionmaker, Channel.WHATSAPP), max_questions=settings.max_questions)
        if llm is not None
        else None
    )
    # Built even without an LLM: it also serves "Sign in with WhatsApp".
    app.state.whatsapp_handler = WhatsAppCitizenHandler(
        sessionmaker,
        wa_agent,
        settings.consent_version,
        speech=speech,
        client=wa_client,
        default_language=speech_settings.speech_default_language,
        voice_replies=speech_settings.speech_voice_replies,
        settings=settings,
    )
    if settings.whatsapp_configured and wa_client is not None:
        app.include_router(
            whatsapp.build_router(
                verify_token=settings.whatsapp_verify_token.get_secret_value(),
                app_secret=settings.whatsapp_app_secret.get_secret_value(),
                on_message=app.state.whatsapp_handler,
                client=wa_client,
                is_new_message=lambda message_id: claim_message(sessionmaker, message_id),
            )
        )
    else:
        log.info("WhatsApp webhook disabled (not configured, or no LLM provider)")

    return app

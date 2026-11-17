"""HTTP server. Run with: uvicorn --factory hirefinch.app:create_app"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .api import ROUTERS
from .api.auth import SecurityMiddleware
from .config import Settings, get_settings
from .db import paths
from .errors import ServiceError
from .runtime import Runtime, build_runtime
from .scheduler import ensure_tasks, run_forever
from .services.applications import recover_incomplete
from .services.accounts import ensure_superadmin_role
from .config import BRAND

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, runtime: Runtime | None = None) -> FastAPI:
    settings = settings or get_settings()
    paths.configure(settings.data_dir, settings.artifacts_dir)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    rt = runtime or build_runtime(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with rt.sessionmaker() as db:
            recovered = await recover_incomplete(db)  # before anything else can submit
            await ensure_superadmin_role(db, settings)
            await db.commit()
        if recovered:
            log.warning("%d interrupted submission(s) need verification; none were resubmitted", recovered)
        await ensure_tasks(rt)
        stop = asyncio.Event()
        task = asyncio.create_task(run_forever(rt, stop)) if settings.scheduler_enabled else None
        yield
        stop.set()
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=10)
        await rt.close()

    show_docs = settings.environment != "production"
    app = FastAPI(title=BRAND, lifespan=lifespan, docs_url="/api/docs" if show_docs else None, redoc_url=None,
                  openapi_url="/api/openapi.json" if show_docs else None)
    app.state.settings = settings
    app.state.runtime = rt
    app.add_middleware(SecurityMiddleware)

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e.get("loc", [])), "msg": str(e.get("msg", "")).removeprefix("Value error, ")}
                   for e in exc.errors()]
        # "phone: use digits…" rather than ": Value error, phone: …" for checks that span a whole form
        return JSONResponse({"error": "invalid_request", "message": "; ".join(
            (f"{field}: {d['msg']}" if (field := ".".join(str(x) for x in d["loc"][1:])) else d["msg"]) for d in details),
            "detail": details}, status_code=422)

    @app.post("/api/client-errors", status_code=204, include_in_schema=False)
    async def client_error(request: Request) -> None:
        """Browser errors (a page that crashed on someone's phone), written to the server log only.
        Rate-limited per address and size-capped; nothing is stored or echoed back."""
        ip = request.client.host if request.client else "unknown"
        if not await rt.limiter.hit(f"client-error:{ip}", 30, 3600):
            return None
        try:
            data = await request.json()
        except Exception:
            return None
        fields = {k: str(data.get(k, ""))[:limit] for k, limit in (("message", 500), ("where", 200), ("path", 200),
                                                                    ("agent", 300), ("stack", 1500))} if isinstance(data, dict) else {}
        logging.getLogger("hirefinch.client").warning("browser error on %s: %s | %s | %s\n%s", fields.get("path"),
                                                      fields.get("message"), fields.get("where"), fields.get("agent"),
                                                      fields.get("stack"))
        return None

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready() -> JSONResponse:
        try:
            async with rt.sessionmaker() as db:
                await db.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"status": "database unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    for router in ROUTERS:
        app.include_router(router)
    return app

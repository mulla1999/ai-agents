"""Double-submit CSRF protection for state-changing API requests."""

from __future__ import annotations

import hmac

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from .sessions import CSRF_COOKIE, CSRF_HEADER

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CSRFMiddleware(BaseHTTPMiddleware):
    """Every non-GET request under /api must echo the ``saathi_csrf`` cookie in ``X-CSRF-Token``.

    A cross-site page cannot read our cookie, so it cannot forge the header. The signed WhatsApp
    webhook lives outside /api and is not affected.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in SAFE_METHODS and request.url.path.startswith("/api/"):
            cookie = request.cookies.get(CSRF_COOKIE, "")
            header = request.headers.get(CSRF_HEADER, "")
            if not cookie or not hmac.compare_digest(cookie.encode(), header.encode()):
                return JSONResponse({"error": "csrf_failed", "message": "missing or invalid CSRF token"}, 403)
        return await call_next(request)

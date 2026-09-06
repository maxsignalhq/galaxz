import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_EXEMPT_ROUTES = {
    ("GET", "/health"),
    ("GET", "/status"),
    ("GET", "/agents"),
    ("GET", "/tasks/recent"),
    ("GET", "/tasks/stats"),
    ("GET", "/review/queue"),
    ("GET", "/orion/status"),
    # GitHub authenticates this endpoint with X-Hub-Signature-256.
    ("POST", "/github/webhook"),
}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._key = os.environ.get("GALAXZ_API_KEY")
        if not self._key:
            logger.warning(
                "[andromeda] GALAXZ_API_KEY not set — auth disabled (local dev mode)"
            )

    async def dispatch(self, request: Request, call_next):
        route_key = (request.method.upper(), request.url.path)
        if route_key in _EXEMPT_ROUTES or not self._key:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if auth_header == f"Bearer {self._key}":
            return await call_next(request)

        return JSONResponse({"error": "unauthorized"}, status_code=401)

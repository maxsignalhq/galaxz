import hmac
import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from core.accounts import Principal, allows, get_account_store, required_permission

logger = logging.getLogger(__name__)

_EXEMPT_ROUTES = {
    ("GET", "/health"),
    ("GET", "/live"),
    ("GET", "/ready"),
    ("GET", "/status"),
    ("GET", "/agents"),
    ("GET", "/tasks/recent"),
    ("GET", "/tasks/stats"),
    ("GET", "/review/queue"),
    ("GET", "/orion/status"),
    # GitHub authenticates this endpoint with X-Hub-Signature-256.
    ("POST", "/github/webhook"),
    # A2A callers authenticate with per-caller tokens inside the A2A handler
    # (core/a2a/server.py), not with GALAXZ_API_KEY.
    ("GET", "/.well-known/agent-card.json"),
    ("POST", "/a2a"),
}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Authenticates a request and authorizes it against the caller's role.

    A request resolves to one principal: the legacy ``GALAXZ_API_KEY`` (admin in the default
    organization), a user API token (``gzt_...``), or ``anonymous`` when no key is set and no
    user exists yet (local dev, unchanged). Routes not declared in ``core.accounts.permissions``
    require ``admin``.
    """

    def __init__(self, app):
        super().__init__(app)
        self._key = os.environ.get("GALAXZ_API_KEY")
        if not self._key:
            logger.warning(
                "[andromeda] GALAXZ_API_KEY not set — auth disabled until a user exists (local dev mode)"
            )

    def _resolve(self, token: str) -> Principal | None:
        if self._key and hmac.compare_digest(token.encode(), self._key.encode()):
            return Principal("api-key", "api-key", "default", "admin")
        if token.startswith("gzt_"):
            principal = get_account_store().authenticate(token)
            if principal is not None:
                return principal
        if not self._key and not get_account_store().has_users():
            return Principal("anonymous", "anonymous", "default", "admin")
        return None

    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        path = request.url.path
        if (method, path) in _EXEMPT_ROUTES:
            request.state.principal = {"id": "exempt-route", "kind": "exempt-route", "organization_id": "default", "role": ""}
            return await call_next(request)

        header = request.headers.get("Authorization", "")
        token = header[len("Bearer "):] if header.startswith("Bearer ") else ""
        request.state.principal = {"id": "unauthenticated", "kind": "unauthenticated", "organization_id": "", "role": ""}
        try:
            principal = self._resolve(token)
        except Exception:
            logger.exception("[andromeda] account store unavailable; refusing request")
            return JSONResponse({"error": "authentication unavailable"}, status_code=503)
        if principal is None:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        request.state.principal = principal.as_state()
        if not allows(principal.role, required_permission(method, path)):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return await call_next(request)

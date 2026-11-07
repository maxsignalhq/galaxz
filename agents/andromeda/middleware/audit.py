"""Record every state-changing request, and every rejected one, in the audit log."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from core.security.audit import audit_event

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


class AuditMiddleware(BaseHTTPMiddleware):
    """Outermost middleware, so it also sees the 401s produced by ``ApiKeyMiddleware``.

    Only the method, path (no query string), status and principal are recorded; never bodies
    or headers.
    """

    async def dispatch(self, request: Request, call_next):
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            method = request.method.upper()
            if method in _MUTATING or status in (401, 403):
                principal = getattr(request.state, "principal", None) or {"id": "unauthenticated", "kind": "unauthenticated"}
                # The sqlite append can wait on a lock held by another process; keep it off the event loop.
                await run_in_threadpool(
                    audit_event,
                    principal["id"],
                    f"http.{method.lower()}",
                    "denied" if status in (401, 403) else "allowed",
                    path=request.url.path,
                    status=status,
                    principal_kind=principal["kind"],
                )

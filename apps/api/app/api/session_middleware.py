from __future__ import annotations

import re
from hmac import compare_digest

from fastapi import Request
from fastapi.responses import JSONResponse

from app.error_handlers import structured_error
from app.settings import Settings

# Only these exact public GET endpoints stay open. There is no public
# "/api/v1/session" route. Demo data files use the exact route shape below;
# prefix matching alone would also expose future "/demo-*" routes.
_PUBLIC_GET_PATHS = frozenset(
    {
        "/api/v1/health",
        "/api/v1/demo",
        "/api/v1/advanced-analyses/capabilities",
    }
)
_PUBLIC_DEMO_DATA_PATTERNS = (re.compile(r"^/api/v1/demo/data/[^/]+$"),)
# SSE progress endpoints must stay token-free because EventSource cannot send
# custom headers. The allowlist matches the exact route shape instead of a
# suffix so a future unrelated "/progress"-suffixed route is NOT auto-public.
_PROGRESS_PATH_PATTERNS = (re.compile(r"^/api/v1/analyses/[^/]+/progress$"),)
# OpenAPI discovery is not on the public allowlist documented in docs/06.
_PROTECTED_DOC_PATHS = frozenset({"/api/docs", "/api/openapi.json"})
_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _unauthorized(code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"detail": structured_error(code, message)},
    )


def _token_matches(request: Request, settings: Settings) -> bool:
    if not settings.session_token:
        return False
    supplied = request.headers.get("X-ResearchPath-Token", "")
    return compare_digest(supplied, settings.session_token)


def session_guard(request: Request, settings: Settings) -> JSONResponse | None:
    """Return a 403 response when a data-touching request lacks the session token.

    Mutations and data-exposing GET endpoints require the ResearchPath session
    token.  Health, demo, capability registry and the exact SSE progress route
    stay open: SSE EventSource cannot send custom headers, and those endpoints
    expose no project data.
    """
    path = request.url.path

    if path in _PROTECTED_DOC_PATHS:
        if not _token_matches(request, settings):
            return _unauthorized(
                "SESSION_TOKEN_REQUIRED",
                "缺少或无效的 ResearchPath 会话令牌",
            )
        return None

    if not path.startswith("/api/v1/"):
        return None

    if request.method == "GET":
        if (
            path in _PUBLIC_GET_PATHS
            or any(pattern.match(path) for pattern in _PUBLIC_DEMO_DATA_PATTERNS)
            or any(pattern.match(path) for pattern in _PROGRESS_PATH_PATTERNS)
        ):
            return None
    elif request.method == "POST" and path == "/api/v1/session/bootstrap":
        return None
    elif request.method not in _MUTATION_METHODS:
        # HEAD, OPTIONS, TRACE and any future non-standard method never fall
        # through silently: they are explicitly rejected.
        return _unauthorized(
            "SESSION_TOKEN_REQUIRED",
            "缺少或无效的 ResearchPath 会话令牌",
        )

    if not _token_matches(request, settings):
        return _unauthorized(
            "SESSION_TOKEN_REQUIRED",
            "缺少或无效的 ResearchPath 会话令牌",
        )
    return None

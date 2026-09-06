from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("researchpath")


def structured_error(
    code: str,
    message: str,
    details: Any = None,
    remediation: Any = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "details": details,
        "remediation": remediation,
    }


def register_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, str):
            body = structured_error(f"HTTP_{exc.status_code}", detail)
        elif isinstance(detail, dict):
            body = structured_error(
                str(detail.get("code") or f"HTTP_{exc.status_code}"),
                str(detail.get("message") or detail.get("detail") or detail),
                detail.get("details"),
                detail.get("remediation"),
            )
        else:
            # list（校验错误）等形状保持原样，供前端 renderDetail 展示
            body = detail
        return JSONResponse(status_code=exc.status_code, content={"detail": body})

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": structured_error(
                    "INTERNAL_ERROR",
                    "内部错误",
                    None,
                    "查看服务日志后重试；若问题持续，重新运行本次分析。",
                )
            },
        )

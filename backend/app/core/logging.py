"""structlog JSON logging + request-id middleware."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings

# Keys whose values must never appear in logs — case-insensitive substring match.
# Matches ``password``, ``token``, ``key``, ``secret``, ``api_key`` and any
# compound key that contains them (e.g. ``stripe_secret_key``, ``auth_token``).
_SENSITIVE_KEY_RE = re.compile(r"(password|token|key|secret|api_key)", re.IGNORECASE)


def scrub_sensitive_values(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    """Replace values of sensitive keys with ``'***'`` before rendering."""
    for key in list(event_dict):
        if _SENSITIVE_KEY_RE.search(key):
            event_dict[key] = "***"
    return event_dict


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", level=settings.log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            scrub_sensitive_values,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger()


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Bind a request id to structlog contextvars for the lifetime of each request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex)
        client = request.client
        request_ip = client.host if client else None
        structlog.contextvars.bind_contextvars(
            request_id=request_id, path=request.url.path, request_ip=request_ip
        )
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Request-ID"] = request_id
        return response

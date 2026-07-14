"""Domain exception taxonomy → HTTP responses.

Handlers/services raise these; a single FastAPI exception handler renders the
`{"error": {"code", "message"}}` envelope. Status codes match the plan (02_Backend §4).
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """Base for all expected, client-facing errors."""

    code: str = "domain_error"
    status: int = 400

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.__class__.__doc__ or self.code
        super().__init__(self.message)


class ValidationError(DomainError):
    """Request failed validation."""

    code = "validation_error"
    status = 422


class NotFound(DomainError):
    """Resource not found."""

    code = "not_found"
    status = 404


class Unauthorized(DomainError):
    """Authentication required or failed (client should (re)authenticate)."""

    code = "unauthorized"
    status = 401


class Forbidden(DomainError):
    """Authenticated but not allowed."""

    code = "forbidden"
    status = 403


class AccountBanned(Forbidden):
    """The Telegram account is banned — the mini-app shows a dedicated banned screen.

    A distinct ``code`` (vs. a bare Forbidden) lets the client tell "you are banned"
    apart from any other 403 and render support-contact copy instead of a generic error.
    """

    code = "account_banned"


class Conflict(DomainError):
    """Conflicting state (e.g. sold out, duplicate)."""

    code = "conflict"
    status = 409


class RateLimited(DomainError):
    """Too many requests."""

    code = "rate_limited"
    status = 429

    def __init__(self, message: str | None = None, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TermsNotAccepted(DomainError):
    """Terms of Use must be accepted before this action."""

    code = "terms_not_accepted"
    status = 428


class PaymentError(DomainError):
    """Payment provider or processing error."""

    code = "payment_error"
    status = 502


class ProvisioningError(DomainError):
    """iproxy provisioning error."""

    code = "provisioning_error"
    status = 502


async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    headers: dict[str, str] = {}
    if isinstance(exc, RateLimited) and exc.retry_after is not None:
        headers["Retry-After"] = str(exc.retry_after)
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers=headers,
    )

"""Admin auth: login (access JWT + httpOnly refresh cookie), refresh, logout, me."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.api.deps import CurrentAdmin, DbSession, reject_revoked_session
from app.core.config import settings
from app.core.errors import ServiceUnavailable, Unauthorized
from app.core.security import blacklist_token, decode_token, is_blacklisted
from app.models import AdminUser
from app.services import admin_otp
from app.services.auth_admin import authenticate, issue_tokens
from app.services.ratelimit_helpers import login_guard

router = APIRouter(prefix="/api/admin", tags=["admin-auth"])

REFRESH_COOKIE = "bm_refresh"
REFRESH_PATH = "/api/admin/auth"


class LoginBody(BaseModel):
    email: str
    password: str


def _admin_view(admin: AdminUser) -> dict[str, Any]:
    return {"id": admin.id, "email": admin.email, "display_name": admin.display_name,
            "role": admin.role}


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        httponly=True,
        secure=settings.env != "local",  # Secure on staging + prod, not just prod
        samesite="strict",
        path=REFRESH_PATH,
        max_age=settings.admin_refresh_ttl_days * 86400,
    )


@router.post("/auth/login")
async def login(
    body: LoginBody, request: Request, response: Response, session: DbSession
) -> dict[str, Any]:
    """Password first. If this account has a Telegram chat bound, that is only half of it.

    The second factor turns itself on the moment an account is reachable — the owner writes
    a handle, that person opens the bot, and from their next sign-in a code is required.
    Nothing to switch on, and nobody can be locked out by a setting: an account with no
    chat bound signs in exactly as before, and the console shows which is which.
    """
    await login_guard(request.client.host if request.client else "unknown")
    admin = await authenticate(session, email=body.email, password=body.password)
    if admin.telegram_user_id is not None:
        ticket, code = await admin_otp.issue(admin.id)
        try:
            await admin_otp.deliver(admin.telegram_user_id, code)
        except admin_otp.DeliveryFailed as exc:
            # No tokens. A code that never arrived must not become a way in — that would
            # switch the second factor off for exactly the people it exists to stop.
            raise ServiceUnavailable(
                "could not send your sign-in code on Telegram — open the bot, press Start, "
                "and try again"
            ) from exc
        return {
            "otp_required": True,
            "ticket": ticket,
            "expires_in": admin_otp.CODE_TTL_SECONDS,
            "sent_to": f"@{admin.telegram_username}" if admin.telegram_username else None,
        }
    access, refresh = issue_tokens(admin)
    _set_refresh_cookie(response, refresh)
    return {"access_token": access, "admin": _admin_view(admin)}


class OtpBody(BaseModel):
    ticket: str
    code: str


@router.post("/auth/login/otp")
async def login_otp(
    body: OtpBody, request: Request, response: Response, session: DbSession
) -> dict[str, Any]:
    """Second half of the sign-in: the code that was sent to Telegram.

    The ticket is the only thing carried over from step one, and it is good for nothing
    else — it cannot be presented to the console as a session.
    """
    await login_guard(request.client.host if request.client else "unknown")
    admin_id = await admin_otp.verify(body.ticket, body.code)
    if admin_id is None:
        raise Unauthorized("wrong or expired code")
    admin = await session.get(AdminUser, admin_id)
    if admin is None or not admin.is_active:
        # Between the two steps the account can be switched off — the ticket must not
        # outlive that.
        raise Unauthorized("account not found or inactive")
    access, refresh = issue_tokens(admin)
    _set_refresh_cookie(response, refresh)
    return {"access_token": access, "admin": _admin_view(admin)}


@router.post("/auth/refresh")
async def refresh(request: Request, response: Response, session: DbSession) -> dict[str, str]:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise Unauthorized("no refresh token")
    claims = decode_token(token, expected_type="refresh")
    jti = claims.get("jti")
    exp = claims.get("exp")
    # Reject a refresh token that was revoked (logout) or already rotated away.
    if jti and await is_blacklisted(str(jti)):
        raise Unauthorized("refresh token revoked")
    admin = await session.get(AdminUser, int(claims["sub"]))
    if admin is None or not admin.is_active:
        raise Unauthorized("admin not found or inactive")
    # The same revocation check as on the access token. Without it here the whole thing is
    # decorative: an old refresh cookie would simply mint a new access token and the
    # revoked session would carry on rotating itself indefinitely.
    reject_revoked_session(admin, claims)
    # Single-use rotation: burn the just-used refresh token so a captured copy
    # (incl. one replayed after logout) can never mint another session.
    if jti and exp:
        await blacklist_token(str(jti), int(exp))
    access, new_refresh = issue_tokens(admin)  # rotate refresh
    _set_refresh_cookie(response, new_refresh)
    return {"access_token": access}


@router.post("/auth/logout")
async def logout(request: Request, response: Response) -> dict[str, bool]:
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        try:
            claims = decode_token(token, expected_type="refresh")
            jti = claims.get("jti")
            exp = claims.get("exp")
            if jti and exp:
                await blacklist_token(str(jti), int(exp))
        except Unauthorized:
            pass  # expired/invalid refresh — nothing to revoke
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH)
    return {"ok": True}


@router.get("/me")
async def me(admin: CurrentAdmin) -> dict[str, Any]:
    return _admin_view(admin)

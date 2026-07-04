"""Admin auth: login (access JWT + httpOnly refresh cookie), refresh, logout, me."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.api.deps import CurrentAdmin, DbSession
from app.core.config import settings
from app.core.errors import Unauthorized
from app.core.security import blacklist_token, decode_token
from app.models import AdminUser
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
        secure=settings.is_prod,
        samesite="strict",
        path=REFRESH_PATH,
        max_age=settings.admin_refresh_ttl_days * 86400,
    )


@router.post("/auth/login")
async def login(
    body: LoginBody, request: Request, response: Response, session: DbSession
) -> dict[str, Any]:
    await login_guard(request.client.host if request.client else "unknown")
    admin = await authenticate(session, email=body.email, password=body.password)
    access, refresh = issue_tokens(admin)
    _set_refresh_cookie(response, refresh)
    return {"access_token": access, "admin": _admin_view(admin)}


@router.post("/auth/refresh")
async def refresh(request: Request, response: Response, session: DbSession) -> dict[str, str]:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise Unauthorized("no refresh token")
    claims = decode_token(token, expected_type="refresh")
    admin = await session.get(AdminUser, int(claims["sub"]))
    if admin is None or not admin.is_active:
        raise Unauthorized("admin not found or inactive")
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

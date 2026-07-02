"""Combined admin router: mounts auth (login/refresh/logout/me) + domain endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.admin.auth import router as auth_router
from app.api.admin.domain import router as domain_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(domain_router)

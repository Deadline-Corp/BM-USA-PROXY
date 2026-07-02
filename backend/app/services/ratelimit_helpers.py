"""Named rate-limit guards used by routers."""

from __future__ import annotations

from app.core.ratelimit import enforce


async def order_guard(user_id: int) -> None:
    await enforce(f"orders:{user_id}", limit=10, window_sec=3600)


async def login_guard(ip: str) -> None:
    await enforce(f"login:{ip}", limit=10, window_sec=60)

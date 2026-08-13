"""Changing an operator's password has to end the sessions they already hold.

The scenario this exists for: someone leaves, their password is changed, and they keep
working access anyway. The refresh cookie lives 14 days and rotates itself, so before this
they had a fortnight — with a console that decides which wallet addresses customer
payments are sent to.

Both doors are tested, because closing one is worse than closing neither: an old refresh
cookie that can still mint access tokens makes the whole thing decorative.
"""

from __future__ import annotations

import pytest_asyncio
from app.api import deps
from app.core.config import settings
from app.core.redis import redis_client
from app.core.security import hash_password
from app.main import app
from app.models import AdminUser
from httpx import ASGITransport, AsyncClient
from scripts.seed import seed_admin, seed_settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

LEAVER = "leaver@test.local"
LEAVER_PW = "leaver-pw-123456"


@pytest_asyncio.fixture
async def ctx(engine):
    """An owner session plus a second account standing in for the departing operator."""
    await redis_client.flushdb()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await seed_settings(s)
        await seed_admin(s)
        s.add(
            AdminUser(
                email=LEAVER, display_name="Leaver", role="operator",
                password_hash=hash_password(LEAVER_PW), is_active=True,
            )
        )
        await s.commit()

    async def _db():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[deps.db_session] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as boss:
        pwd = settings.seed_admin_password
        assert pwd is not None
        r = await boss.post(
            "/api/admin/auth/login",
            json={"email": settings.seed_admin_email, "password": pwd.get_secret_value()},
        )
        boss.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as leaver:
            r = await leaver.post(
                "/api/admin/auth/login", json={"email": LEAVER, "password": LEAVER_PW}
            )
            assert r.status_code == 200, r.text
            leaver.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
            yield boss, leaver, maker
    app.dependency_overrides.clear()


async def _leaver_id(maker) -> int:
    async with maker() as s:
        return await s.scalar(select(AdminUser.id).where(AdminUser.email == LEAVER))


async def test_changing_the_password_ends_the_open_session(ctx) -> None:
    boss, leaver, maker = ctx
    assert (await leaver.get("/api/admin/me")).status_code == 200  # working before

    admin_id = await _leaver_id(maker)
    r = await boss.patch(f"/api/admin/admins/{admin_id}", json={"password": "brand-new-pw-99"})
    assert r.status_code == 200, r.text

    # The token in their browser is now refused — not at expiry, immediately.
    gone = await leaver.get("/api/admin/me")
    assert gone.status_code == 401, gone.text

    # …and the refresh cookie cannot mint a replacement, which is the door that matters:
    # it rotates itself and would otherwise keep the session alive for a fortnight.
    again = await leaver.post("/api/admin/auth/refresh")
    assert again.status_code == 401, again.text


async def test_deactivating_ends_the_open_session_too(ctx) -> None:
    boss, leaver, maker = ctx
    admin_id = await _leaver_id(maker)
    assert (await boss.patch(
        f"/api/admin/admins/{admin_id}", json={"is_active": False}
    )).status_code == 200
    assert (await leaver.get("/api/admin/me")).status_code in (401, 403)
    assert (await leaver.post("/api/admin/auth/refresh")).status_code == 401


async def test_the_new_password_still_works(ctx) -> None:
    """Revocation must end sessions, not the account — the replacement operator signs in."""
    boss, _leaver, maker = ctx
    admin_id = await _leaver_id(maker)
    await boss.patch(f"/api/admin/admins/{admin_id}", json={"password": "brand-new-pw-99"})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as newcomer:
        r = await newcomer.post(
            "/api/admin/auth/login", json={"email": LEAVER, "password": "brand-new-pw-99"}
        )
        assert r.status_code == 200, r.text
        newcomer.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        assert (await newcomer.get("/api/admin/me")).status_code == 200
        # and the old password is dead
        assert (await newcomer.post(
            "/api/admin/auth/login", json={"email": LEAVER, "password": LEAVER_PW}
        )).status_code == 401


async def test_an_unrelated_change_leaves_sessions_alone(ctx) -> None:
    """Renaming somebody must not sign them out — revocation is for password and off."""
    boss, leaver, maker = ctx
    admin_id = await _leaver_id(maker)
    assert (await boss.patch(
        f"/api/admin/admins/{admin_id}", json={"display_name": "Same Person, New Name"}
    )).status_code == 200
    assert (await leaver.get("/api/admin/me")).status_code == 200


async def test_other_accounts_are_untouched(ctx) -> None:
    """Revocation is per account: ending one operator's sessions must not end everyone's."""
    boss, _leaver, maker = ctx
    admin_id = await _leaver_id(maker)
    await boss.patch(f"/api/admin/admins/{admin_id}", json={"password": "brand-new-pw-99"})
    assert (await boss.get("/api/admin/me")).status_code == 200

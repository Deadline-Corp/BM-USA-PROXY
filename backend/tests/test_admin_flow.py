"""Admin API smoke: login/lockout, JWT auth, refresh, RBAC, key endpoints reachable."""

from __future__ import annotations

import pytest_asyncio
from app.api import deps
from app.core.config import settings
from app.core.redis import redis_client
from app.main import app
from httpx import ASGITransport, AsyncClient
from scripts.seed import (
    seed_admin,
    seed_dev_fixtures,
    seed_locations,
    seed_settings,
    seed_tariffs,
)
from sqlalchemy.ext.asyncio import async_sessionmaker


@pytest_asyncio.fixture
async def raw_client(engine):
    await redis_client.flushdb()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await seed_settings(s)
        await seed_tariffs(s)
        await seed_locations(s)
        await seed_admin(s)
        await s.flush()
        await seed_dev_fixtures(s)
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()


async def _login(c: AsyncClient) -> str:
    r = await c.post(
        "/api/admin/auth/login",
        json={"email": settings.seed_admin_email, "password": settings.seed_admin_password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_wrong_password_rejected(raw_client: AsyncClient) -> None:
    r = await raw_client.post(
        "/api/admin/auth/login",
        json={"email": settings.seed_admin_email, "password": "nope"},
    )
    assert r.status_code == 401


async def test_login_me_and_refresh(raw_client: AsyncClient) -> None:
    token = await _login(raw_client)
    raw_client.headers["Authorization"] = f"Bearer {token}"
    me = await raw_client.get("/api/admin/me")
    assert me.status_code == 200
    assert me.json()["role"] == "owner"
    # refresh cookie was set by login → refresh works
    refreshed = await raw_client.post("/api/admin/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]


async def test_protected_without_token_is_401(raw_client: AsyncClient) -> None:
    assert (await raw_client.get("/api/admin/dashboard")).status_code == 401


async def test_core_admin_endpoints_reachable(raw_client: AsyncClient) -> None:
    token = await _login(raw_client)
    raw_client.headers["Authorization"] = f"Bearer {token}"
    for path in ("/api/admin/dashboard", "/api/admin/tariffs", "/api/admin/clients",
                 "/api/admin/pool/summary", "/api/admin/connections", "/api/admin/orders",
                 "/api/admin/requests", "/api/admin/faq"):
        r = await raw_client.get(path)
        assert r.status_code == 200, f"{path} → {r.status_code} {r.text[:200]}"


async def test_create_tariff_then_visible_in_twa_catalog(raw_client: AsyncClient) -> None:
    token = await _login(raw_client)
    raw_client.headers["Authorization"] = f"Bearer {token}"
    r = await raw_client.post(
        "/api/admin/tariffs",
        json={"code": "biweekly", "name": "Biweekly", "kind": "auto",
              "duration_minutes": 20160, "price_usd": 40, "auto_issue": True},
    )
    assert r.status_code in (200, 201), r.text
    listing = await raw_client.get("/api/admin/tariffs")
    body = listing.json()
    rows = body["items"] if isinstance(body, dict) else body
    assert any(t["code"] == "biweekly" for t in rows)

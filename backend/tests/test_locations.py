"""Admin CRUD for locations (cities) — the catalog an operator assigns phones to.

Covers: create + normalization, the city+state uniqueness conflict, renaming into a
conflict, toggling active/inactive, and the delete guard — a location with connections
still on it can only be deactivated, never deleted, since the FK has no cascade and an
unconditional delete would either violate it or silently orphan devices onto no city.

Everything here goes through the real FastAPI route + real Postgres session (the `ctx`
fixture below, matching test_admin_delete.py's shape) — no mocking of the endpoints or
queries under test.
"""

from __future__ import annotations

import pytest_asyncio
from app.api import deps
from app.core.config import settings
from app.core.redis import redis_client
from app.main import app
from app.models import Connection
from httpx import ASGITransport, AsyncClient
from scripts.seed import seed_admin, seed_settings
from sqlalchemy.ext.asyncio import async_sessionmaker


@pytest_asyncio.fixture
async def ctx(engine):
    await redis_client.flushdb()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await seed_settings(s)
        await seed_admin(s)
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
        pwd = settings.seed_admin_password
        assert pwd is not None
        r = await c.post(
            "/api/admin/auth/login",
            json={"email": settings.seed_admin_email, "password": pwd.get_secret_value()},
        )
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield c, maker
    app.dependency_overrides.clear()


async def _create_location(client: AsyncClient, city: str, state_code: str, **extra) -> dict:
    r = await client.post(
        "/api/admin/locations", json={"city": city, "state_code": state_code, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_location(ctx) -> None:
    client, _maker = ctx
    body = await _create_location(client, "  Austin  ", "tx")
    # City trimmed, state code upper-cased — the only normalization the spec asked for.
    assert body["city"] == "Austin"
    assert body["state_code"] == "TX"
    assert body["is_active"] is True
    assert body["sort_order"] == 100
    assert body["connections_count"] == 0

    listing = (await client.get("/api/admin/locations")).json()
    assert any(loc["city"] == "Austin" and loc["state_code"] == "TX" for loc in listing)

    # Same baseline RBAC check every admin endpoint gets in this suite.
    del client.headers["Authorization"]
    assert (await client.get("/api/admin/locations")).status_code == 401


async def test_create_location_duplicate_conflicts(ctx) -> None:
    client, _maker = ctx
    await _create_location(client, "Austin", "TX")

    r = await client.post("/api/admin/locations", json={"city": "Austin", "state_code": "TX"})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "conflict"

    # Whitespace/case variants collide too — city is trimmed and state_code upper-cased
    # before the uniqueness check runs, both here and on create.
    r2 = await client.post("/api/admin/locations", json={"city": " Austin ", "state_code": "tx"})
    assert r2.status_code == 409, r2.text


async def test_patch_location_rename_and_conflict(ctx) -> None:
    client, _maker = ctx
    a = await _create_location(client, "Austin", "TX")
    await _create_location(client, "Boston", "MA")

    r = await client.patch(
        f"/api/admin/locations/{a['id']}",
        json={"city": "Round Rock", "sort_order": 5, "is_active": False},
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["city"] == "Round Rock"
    assert updated["state_code"] == "TX"  # untouched field survives a partial patch
    assert updated["sort_order"] == 5
    assert updated["is_active"] is False

    # Renaming onto an existing city+state is the same conflict create() raises.
    conflict = await client.patch(
        f"/api/admin/locations/{a['id']}", json={"city": "Boston", "state_code": "MA"}
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "conflict"


async def test_toggle_location(ctx) -> None:
    client, _maker = ctx
    loc = await _create_location(client, "Austin", "TX", is_active=False)
    assert loc["is_active"] is False

    r = await client.post(f"/api/admin/locations/{loc['id']}/toggle")
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True


async def test_delete_location_with_connections_blocked(ctx) -> None:
    client, maker = ctx
    loc = await _create_location(client, "Austin", "TX")
    async with maker() as s:
        s.add(
            Connection(
                iproxy_connection_id="dev-austin-0",
                name="Austin #1",
                location_id=int(loc["id"]),
            )
        )
        await s.commit()

    # The list endpoint's aggregate count already sees the attached connection.
    listing = (await client.get("/api/admin/locations")).json()
    row = next(r for r in listing if r["id"] == loc["id"])
    assert row["connections_count"] == 1

    r = await client.delete(f"/api/admin/locations/{loc['id']}")
    assert r.status_code == 409, r.text
    message = r.json()["error"]["message"]
    assert "1" in message
    assert "deactivate" in message.lower()

    # Rejected delete leaves it exactly as it was — still there, still active — and the
    # suggested alternative (deactivate) works fine on the very same row.
    listing_after = (await client.get("/api/admin/locations")).json()
    assert any(r["id"] == loc["id"] for r in listing_after)
    assert (await client.post(f"/api/admin/locations/{loc['id']}/toggle")).status_code == 200


async def test_delete_location_without_connections_succeeds(ctx) -> None:
    client, _maker = ctx
    loc = await _create_location(client, "Austin", "TX")

    r = await client.delete(f"/api/admin/locations/{loc['id']}")
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": True}

    listing = (await client.get("/api/admin/locations")).json()
    assert all(row["id"] != loc["id"] for row in listing)

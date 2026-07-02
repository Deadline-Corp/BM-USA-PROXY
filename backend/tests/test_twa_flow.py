"""End-to-end TWA customer flow against the real app (ASGI), test Postgres + Redis.

Covers: catalog, Terms gate (428 → accept), buy → mock-pay → provisioning → My Access,
trial one-per-user + swap semantics.
"""

from __future__ import annotations

import pytest_asyncio
from app.api import deps
from app.core.redis import redis_client
from app.main import app
from httpx import ASGITransport, AsyncClient
from scripts.seed import seed_dev_fixtures, seed_locations, seed_settings, seed_tariffs
from sqlalchemy.ext.asyncio import async_sessionmaker

IDENTITY = {
    "tg_user_id": 700001,
    "tg_username": "buyer",
    "first_name": "Buyer",
    "last_name": None,
    "lang": "en",
    "start_param": None,
}


@pytest_asyncio.fixture
async def client(engine):
    await redis_client.flushdb()  # DB 15 — isolated
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await seed_settings(s)
        await seed_tariffs(s)
        await seed_locations(s)
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
    app.dependency_overrides[deps.twa_identity] = lambda: dict(IDENTITY)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()


async def _accept_terms(client: AsyncClient) -> None:
    terms = (await client.get("/api/twa/terms")).json()
    r = await client.post(
        "/api/twa/terms/accept",
        json={"version": terms["version"], "answers": {"email": "buyer@example.com"}},
    )
    assert r.status_code == 200


async def test_catalog_has_real_data(client: AsyncClient) -> None:
    r = await client.get("/api/twa/catalog")
    assert r.status_code == 200
    data = r.json()
    codes = {t["code"] for t in data["tariffs"]}
    assert {"trial", "daily", "weekly", "monthly"} <= codes
    assert data["carriers"] == ["AT&T", "T-Mobile", "Verizon"]
    assert len(data["locations"]) == 9
    assert data["trial_available"] is True


async def test_terms_gate_blocks_then_allows(client: AsyncClient) -> None:
    # buying before accepting Terms is blocked (428)
    r = await client.post("/api/twa/orders", json={"tariff_code": "daily"})
    assert r.status_code == 428
    await _accept_terms(client)
    r = await client.post("/api/twa/orders", json={"tariff_code": "daily"})
    assert r.status_code == 200
    body = r.json()
    assert body["order"]["status"] == "awaiting_payment"
    assert body["invoice"]["amount_usd"] == 10.0


async def test_buy_pay_and_receive_access(client: AsyncClient) -> None:
    await _accept_terms(client)
    order = (await client.post("/api/twa/orders", json={"tariff_code": "daily"})).json()
    pid = order["order"]["public_id"]

    paid = await client.post(f"/api/twa/orders/{pid}/_mock_pay")
    assert paid.status_code == 200
    assert paid.json()["status"] == "completed"

    status = (await client.get(f"/api/twa/orders/{pid}")).json()
    assert status["status"] == "completed"
    access_pid = status["access_public_id"]
    assert access_pid

    accesses = (await client.get("/api/twa/accesses")).json()
    assert len(accesses["active"]) == 1

    detail = (await client.get(f"/api/twa/accesses/{access_pid}")).json()
    assert detail["credentials"]["host"]
    assert detail["credentials"]["socks5_port"] == 1080
    assert detail["swap_left"] == 0  # daily has no swaps


async def test_trial_is_one_per_user_with_one_swap(client: AsyncClient) -> None:
    await _accept_terms(client)
    first = await client.post("/api/twa/orders", json={"tariff_code": "trial"})
    assert first.status_code == 200
    assert first.json()["order"]["status"] == "completed"  # free → instant issue

    # trial access should allow exactly one swap
    accesses = (await client.get("/api/twa/accesses")).json()
    trial_access = accesses["active"][0]["public_id"]
    detail = (await client.get(f"/api/twa/accesses/{trial_access}")).json()
    assert detail["swap_left"] == 1

    # a second trial is refused
    second = await client.post("/api/twa/orders", json={"tariff_code": "trial"})
    assert second.status_code == 422


async def test_trial_swap_keeps_expiry_and_decrements(client: AsyncClient) -> None:
    await _accept_terms(client)
    await client.post("/api/twa/orders", json={"tariff_code": "trial"})
    accesses = (await client.get("/api/twa/accesses")).json()
    pid = accesses["active"][0]["public_id"]
    before = (await client.get(f"/api/twa/accesses/{pid}")).json()

    r = await client.post(f"/api/twa/accesses/{pid}/swap", json={})
    assert r.status_code == 200
    after = (await client.get(f"/api/twa/accesses/{pid}")).json()
    assert after["swap_left"] == 0
    assert after["expires_at"] == before["expires_at"]  # timer unchanged
    # second swap refused
    assert (await client.post(f"/api/twa/accesses/{pid}/swap", json={})).status_code == 403

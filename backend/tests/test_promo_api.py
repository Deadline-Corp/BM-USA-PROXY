"""Promo codes over HTTP: the console creates them, the mini app spends them.

`test_promos.py` covers the rules. This covers the two surfaces an operator and a buyer
actually touch, and the seam between them — a code created in the console has to be the
same code the checkout accepts, and the money the buyer is charged has to be the money the
quote promised. Every one of those crosses a serialisation boundary the service tests never
see.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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

IDENTITY = {
    "tg_user_id": 700501,
    "tg_username": "promobuyer",
    "first_name": "Promo",
    "last_name": None,
    "lang": "en",
    "start_param": None,
}


@pytest_asyncio.fixture
async def client(engine):
    """One client wearing both hats.

    The console and the mini app are separate routers on one app, and the whole point here
    is that a code crosses between them — splitting this into two fixtures would mean two
    databases and nothing to test.
    """
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
    app.dependency_overrides[deps.twa_identity] = lambda: dict(IDENTITY)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        pwd = settings.seed_admin_password
        assert pwd is not None
        login = await c.post(
            "/api/admin/auth/login",
            json={"email": settings.seed_admin_email, "password": pwd.get_secret_value()},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c
    app.dependency_overrides.clear()


async def _accept_terms(c: AsyncClient) -> None:
    terms = (await c.get("/api/twa/terms")).json()
    r = await c.post(
        "/api/twa/terms/accept",
        json={"version": terms["version"], "answers": {"email": "promo@example.com"}},
    )
    assert r.status_code == 200, r.text


async def _create(c: AsyncClient, **body) -> dict:
    payload = {"code": "SUMMER", "percent_off": 20, "applies_to": "any"}
    payload.update(body)
    r = await c.post("/api/admin/promo-codes", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def _codes(c: AsyncClient) -> list[dict]:
    r = await c.get("/api/admin/promo-codes")
    assert r.status_code == 200, r.text
    return r.json()["items"]


# ── the console ───────────────────────────────────────────────────────────


async def test_a_created_code_comes_back_in_the_list_ready_to_use(client: AsyncClient) -> None:
    created = await _create(client, code="summer", note="August campaign")
    # Upper-cased on the way in, so the list shows what an operator reads out to a client.
    assert created["code"] == "SUMMER"
    assert created["state"] == "active"
    assert created["used"] == 0

    listed = await _codes(client)
    assert [p["code"] for p in listed] == ["SUMMER"]
    assert listed[0]["note"] == "August campaign"


async def test_two_live_codes_cannot_share_a_name(client: AsyncClient) -> None:
    await _create(client, code="SUMMER")
    r = await client.post(
        "/api/admin/promo-codes",
        json={"code": "summer", "percent_off": 50, "applies_to": "any"},
    )
    assert r.status_code == 409, r.text


async def test_an_expiry_already_in_the_past_is_refused(client: AsyncClient) -> None:
    r = await client.post(
        "/api/admin/promo-codes",
        json={
            "code": "STALE",
            "percent_off": 10,
            "applies_to": "any",
            "expires_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 422, r.text


async def test_a_window_that_ends_before_it_starts_is_refused(client: AsyncClient) -> None:
    start = datetime.now(UTC) + timedelta(days=10)
    r = await client.post(
        "/api/admin/promo-codes",
        json={
            "code": "BACKWARDS",
            "percent_off": 10,
            "applies_to": "any",
            "starts_at": start.isoformat(),
            "expires_at": (start - timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 422, r.text


async def test_a_scheduled_code_says_so_rather_than_looking_active(client: AsyncClient) -> None:
    await _create(
        client,
        code="AUTUMN",
        starts_at=(datetime.now(UTC) + timedelta(days=7)).isoformat(),
    )
    listed = await _codes(client)
    assert listed[0]["state"] == "scheduled"


async def test_a_deleted_code_leaves_the_list_and_stops_working(client: AsyncClient) -> None:
    created = await _create(client, code="GONE")
    await _accept_terms(client)

    dropped = await client.delete(f"/api/admin/promo-codes/{created['id']}")
    assert dropped.status_code == 200, dropped.text

    assert await _codes(client) == []
    refused = await client.post(
        "/api/twa/promo/check", json={"code": "GONE", "tariff_code": "daily"}
    )
    assert refused.status_code == 422


# ── the checkout ──────────────────────────────────────────────────────────


async def test_the_quote_prices_the_whole_order_not_one_proxy(client: AsyncClient) -> None:
    await _create(client, code="SUMMER", percent_off=20)
    await _accept_terms(client)

    r = await client.post(
        "/api/twa/promo/check",
        json={"code": "summer", "tariff_code": "daily", "quantity": 3},
    )
    assert r.status_code == 200, r.text
    quote = r.json()
    assert quote["subtotal_usd"] == 30.0
    assert quote["amount_off_usd"] == 6.0
    assert quote["total_usd"] == 24.0


async def test_a_rejection_carries_a_message_the_buyer_can_act_on(client: AsyncClient) -> None:
    await _accept_terms(client)
    r = await client.post(
        "/api/twa/promo/check", json={"code": "NOSUCHTHING", "tariff_code": "daily"}
    )
    assert r.status_code == 422
    # Shown to the buyer as it is, so it has to name the problem rather than the layer.
    assert "not found" in r.json()["error"]["message"]


async def test_the_order_is_charged_the_quoted_total_and_the_use_is_spent(
    client: AsyncClient,
) -> None:
    """The seam. A quote nobody honours is worse than no promo field at all."""
    await _create(client, code="HALF", percent_off=50)
    await _accept_terms(client)

    quote = (
        await client.post(
            "/api/twa/promo/check", json={"code": "HALF", "tariff_code": "daily"}
        )
    ).json()
    assert quote["total_usd"] == 5.0

    order = await client.post(
        "/api/twa/orders", json={"tariff_code": "daily", "promo_code": "half"}
    )
    assert order.status_code == 200, order.text
    body = order.json()
    assert body["order"]["amount_usd"] == 5.0
    assert body["invoice"]["amount_usd"] == 5.0

    listed = await _codes(client)
    assert listed[0]["used"] == 1


async def test_a_cancelled_order_hands_the_use_back(client: AsyncClient) -> None:
    created = await _create(client, code="ONESHOT", percent_off=10, max_uses=1)
    await _accept_terms(client)

    order = await client.post(
        "/api/twa/orders", json={"tariff_code": "daily", "promo_code": "ONESHOT"}
    )
    assert order.status_code == 200, order.text
    assert (await _codes(client))[0]["used"] == 1

    public_id = order.json()["order"]["public_id"]
    cancelled = await client.post(f"/api/twa/orders/{public_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text

    listed = await _codes(client)
    assert listed[0]["used"] == 0
    assert listed[0]["state"] == "active"
    assert listed[0]["id"] == created["id"]


async def test_a_start_date_already_gone_is_refused(client: AsyncClient) -> None:
    """The client made a code dated 1 September on the 9th and it went live backdated.

    The floor here is a day wide on purpose: this process does not know what date it is
    where the operator is sitting, and their local midnight today can be most of a day
    behind UTC. Refusing anything before *today* is the console's job, against the
    operator's own calendar — see PromoFormModal. This catches the rest.
    """
    r = await client.post(
        "/api/admin/promo-codes",
        json={
            "code": "BACKDATED",
            "percent_off": 10,
            "applies_to": "any",
            "starts_at": (datetime.now(UTC) - timedelta(days=8)).isoformat(),
        },
    )
    assert r.status_code == 422, r.text
    assert "past" in r.json()["error"]["message"]


async def test_a_start_date_of_today_is_fine_whatever_the_operators_timezone(
    client: AsyncClient,
) -> None:
    """Local midnight today is in the past in UTC for most of the world.

    A naive "starts_at must not be before now" would have refused every code an operator
    east of Greenwich created for today — which is the ordinary case, not the edge one.
    """
    r = await client.post(
        "/api/admin/promo-codes",
        json={
            "code": "TODAY",
            "percent_off": 10,
            "applies_to": "any",
            "starts_at": (datetime.now(UTC) - timedelta(hours=14)).isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["state"] == "active"


# ── who used what ─────────────────────────────────────────────────────────


async def test_the_usage_list_says_who_bought_what_with_which_code(
    client: AsyncClient,
) -> None:
    await _create(client, code="SUMMER", percent_off=20)
    await _accept_terms(client)
    order = await client.post(
        "/api/twa/orders", json={"tariff_code": "daily", "quantity": 2, "promo_code": "SUMMER"}
    )
    assert order.status_code == 200, order.text

    r = await client.get("/api/admin/promo-usage")
    assert r.status_code == 200, r.text
    rows = r.json()["items"]
    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "SUMMER"
    assert row["percent_off"] == 20
    assert row["client"] == "@promobuyer"
    # The plan's own name, not its code — "Daily" is what the operator sells.
    assert row["plan"] == "Daily"
    assert row["quantity"] == 2
    assert row["discount_usd"] == 4.0
    assert row["amount_usd"] == 16.0
    assert row["is_extension"] is False
    assert row["code_deleted"] is False
    assert row["status"] == "awaiting_payment"


async def test_a_cancelled_order_stays_in_the_history_even_though_the_use_came_back(
    client: AsyncClient,
) -> None:
    """Why this list is read off orders rather than off redemptions.

    Cancelling deletes the redemption row — that deletion is what hands the use back to the
    code. A history built on redemptions would therefore lose every attempt that did not
    become a sale, which is precisely the half an operator asking "who has been using this
    code" is trying to find.
    """
    await _create(client, code="ONESHOT", percent_off=10, max_uses=1)
    await _accept_terms(client)
    order = await client.post(
        "/api/twa/orders", json={"tariff_code": "daily", "promo_code": "ONESHOT"}
    )
    assert order.status_code == 200, order.text
    public_id = order.json()["order"]["public_id"]
    assert (await client.post(f"/api/twa/orders/{public_id}/cancel")).status_code == 200

    # The use is back on the code…
    assert (await _codes(client))[0]["used"] == 0
    # …and the attempt is still on the record.
    rows = (await client.get("/api/admin/promo-usage")).json()["items"]
    assert len(rows) == 1
    assert rows[0]["code"] == "ONESHOT"
    assert rows[0]["status"] == "cancelled"


async def test_a_retired_codes_sales_survive_it_and_say_so(client: AsyncClient) -> None:
    created = await _create(client, code="GONE", percent_off=50)
    await _accept_terms(client)
    assert (
        await client.post("/api/twa/orders", json={"tariff_code": "daily", "promo_code": "GONE"})
    ).status_code == 200
    assert (await client.delete(f"/api/admin/promo-codes/{created['id']}")).status_code == 200

    assert await _codes(client) == []
    rows = (await client.get("/api/admin/promo-usage")).json()["items"]
    assert len(rows) == 1
    assert rows[0]["code"] == "GONE"
    # Marked, because an operator who cannot find the code in the list above would
    # otherwise read the row as a mistake.
    assert rows[0]["code_deleted"] is True


async def test_the_usage_list_can_be_narrowed_to_one_code(client: AsyncClient) -> None:
    await _create(client, code="ALPHA", percent_off=10)
    await _create(client, code="BETA", percent_off=10)
    await _accept_terms(client)
    for code in ("ALPHA", "BETA"):
        assert (
            await client.post(
                "/api/twa/orders", json={"tariff_code": "daily", "promo_code": code}
            )
        ).status_code == 200

    everything = (await client.get("/api/admin/promo-usage")).json()
    assert everything["total"] == 2

    # Lower case, because an operator types what a client said, not what is stored.
    only_beta = (await client.get("/api/admin/promo-usage", params={"code": "beta"})).json()
    assert only_beta["total"] == 1
    assert only_beta["items"][0]["code"] == "BETA"


async def test_orders_without_a_code_stay_out_of_it(client: AsyncClient) -> None:
    await _accept_terms(client)
    assert (await client.post("/api/twa/orders", json={"tariff_code": "daily"})).status_code == 200
    assert (await client.get("/api/admin/promo-usage")).json() == {"items": [], "total": 0}

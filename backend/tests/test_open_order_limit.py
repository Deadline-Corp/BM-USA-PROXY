"""How many unpaid orders one customer may hold at once.

The audit of 2026-08-22 found that nothing stopped a single person from creating orders
until the catalogue was empty: every unpaid order takes its phones off the shelf for the
length of the invoice, and none of it costs anything. The client chose the shape on
2026-09-09 — an operator-set number, three by default.

What is worth testing here is not "the fourth one fails". It is the two ways a limit like
this goes wrong in production: refusing somebody over invoices that have already lapsed but
that the expiry cron has not marked yet, and being walked around through a door nobody
thought to close.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from app.api import deps
from app.core.redis import redis_client
from app.main import app
from app.models import Invoice
from app.services import settings as settings_svc
from httpx import ASGITransport, AsyncClient
from scripts.seed import seed_dev_fixtures, seed_locations, seed_settings, seed_tariffs
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

IDENTITY = {
    "tg_user_id": 700701,
    "tg_username": "hoarder",
    "first_name": "Hoarder",
    "last_name": None,
    "lang": "en",
    "start_param": None,
}


@pytest_asyncio.fixture
async def client(engine):
    await redis_client.flushdb()
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await _accept_terms(c)
        yield c
    app.dependency_overrides.clear()


async def _accept_terms(c: AsyncClient) -> None:
    terms = (await c.get("/api/twa/terms")).json()
    r = await c.post(
        "/api/twa/terms/accept",
        json={"version": terms["version"], "answers": {"email": "hoarder@example.com"}},
    )
    assert r.status_code == 200, r.text


async def _buy(c: AsyncClient, tariff: str = "daily"):
    return await c.post("/api/twa/orders", json={"tariff_code": tariff})


async def _set_limit(engine, value: int) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await settings_svc.set_value(s, "max_open_orders_per_user", value)
        await s.commit()


# ── the limit itself ──────────────────────────────────────────────────────


async def test_the_default_allowance_is_three_and_the_fourth_is_refused(
    client: AsyncClient,
) -> None:
    for i in range(3):
        r = await _buy(client)
        assert r.status_code == 200, f"order {i + 1}: {r.text}"

    fourth = await _buy(client)
    assert fourth.status_code == 409, fourth.text
    body = fourth.json()
    # A plain 409 is what "sold out" uses, and the mini app rendered it as that — telling
    # the buyer the pool was empty when the problem was their own unpaid invoices.
    assert body["error"]["code"] == "too_many_open_orders"
    assert "3" in body["error"]["message"]


async def test_cancelling_one_makes_room_for_the_next(client: AsyncClient) -> None:
    first = await _buy(client)
    for _ in range(2):
        assert (await _buy(client)).status_code == 200
    assert (await _buy(client)).status_code == 409

    public_id = first.json()["order"]["public_id"]
    assert (await client.post(f"/api/twa/orders/{public_id}/cancel")).status_code == 200

    assert (await _buy(client)).status_code == 200


async def test_zero_turns_the_limit_off(client: AsyncClient, engine) -> None:
    await _set_limit(engine, 0)
    for i in range(5):
        assert (await _buy(client)).status_code == 200, f"order {i + 1}"


async def test_one_means_one(client: AsyncClient, engine) -> None:
    await _set_limit(engine, 1)
    assert (await _buy(client)).status_code == 200
    second = await _buy(client)
    assert second.status_code == 409
    # Singular, because "you already have 1 unpaid orders" is the kind of thing a customer
    # screenshots.
    assert "1 unpaid order " in second.json()["error"]["message"]


# ── the two ways it goes wrong ────────────────────────────────────────────


async def test_an_invoice_past_its_deadline_stops_counting_before_the_sweep_marks_it(
    client: AsyncClient, engine
) -> None:
    """The failure this test exists for.

    `expire_invoices` is a cron. Between an invoice running out and the cron getting to it,
    the order is still `awaiting_payment` — and a limit that counted those rows would tell
    a customer they have three unpaid orders when all three are dead. They would have no
    way to act on it either: cancelling an expired order is not something the app offers.
    """
    for _ in range(3):
        assert (await _buy(client)).status_code == 200
    assert (await _buy(client)).status_code == 409

    # Push every invoice past its deadline WITHOUT running the sweep — exactly the state
    # the system is in for up to a minute after each one lapses.
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        invoices = (await s.execute(select(Invoice))).scalars().all()
        assert len(invoices) == 3
        for inv in invoices:
            inv.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await s.commit()

    assert (await _buy(client)).status_code == 200


async def test_a_deposit_still_confirming_keeps_counting_past_its_deadline(
    client: AsyncClient, engine
) -> None:
    """The other half of the same rule.

    An invoice whose deposit is already on-chain outlives its deadline — the watcher
    finalises it and `expire_invoices` refuses to touch it. That order is as open as an
    order gets, and forgetting it here would hand somebody an extra slot for every payment
    they had in flight.
    """
    for _ in range(3):
        assert (await _buy(client)).status_code == 200

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        invoices = (await s.execute(select(Invoice))).scalars().all()
        for inv in invoices:
            inv.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            inv.status = "confirming"
            inv.matched_txid = f"0xdeadbeef{inv.id}"
        await s.commit()

    refused = await _buy(client)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "too_many_open_orders"


async def test_extending_an_access_goes_through_the_same_allowance(
    client: AsyncClient,
) -> None:
    """Extend creates an order and an invoice like any other purchase.

    Leaving it outside the limit would have made it the way around one: fill the allowance
    with purchases, then keep going by pressing Extend.
    """
    trial = await client.post("/api/twa/orders", json={"tariff_code": "trial"})
    assert trial.status_code == 200, trial.text
    order_id = trial.json()["order"]["public_id"]
    access_id = (await client.get(f"/api/twa/orders/{order_id}")).json()["access_public_id"]
    assert access_id

    for _ in range(3):
        assert (await _buy(client)).status_code == 200

    refused = await client.post(
        f"/api/twa/accesses/{access_id}/extend", json={"tariff_code": "daily"}
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "too_many_open_orders"


async def test_the_free_trial_is_never_refused_over_unpaid_orders(
    client: AsyncClient,
) -> None:
    """A free plan is paid the instant it is created, so it can never join the pile.

    Refusing it would be refusing somebody for a reason that is not true about the thing
    they asked for — and the trial is the one purchase where a refusal costs a customer.
    """
    for _ in range(3):
        assert (await _buy(client)).status_code == 200
    assert (await _buy(client)).status_code == 409

    trial = await client.post("/api/twa/orders", json={"tariff_code": "trial"})
    assert trial.status_code == 200, trial.text
    assert trial.json()["order"]["status"] == "completed"

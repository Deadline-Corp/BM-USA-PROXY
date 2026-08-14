"""End-to-end TWA customer flow against the real app (ASGI), test Postgres + Redis.

Covers: catalog, Terms gate (428 → accept), buy → mock-pay → provisioning → My Access,
trial one-per-user + swap semantics.
"""

from __future__ import annotations

import pytest
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


async def test_paid_order_with_no_wallets_configured_gives_clear_error_not_rate_limit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduces the reported incident: an owner opened the mini app, tapped Buy, and only
    ever saw `too many requests for orders:3` — because 0 of the on-chain rails were ever
    saved in the admin console, every attempt failed the same way, and by the time they
    reported it the real error was already hidden behind the order rate limit.

    Two things must both hold now: the failure is a clear `payments_unconfigured` (not a
    bare 500, not a 429), and — because it's certain to fail regardless of how many times the
    buyer tries — it must never consume the 10/hour order_guard budget. Trial is free and
    never touches the payment provider, so it must keep working through all of this.
    """
    from app.services.payments.onchain.config import set_rails_override
    from app.services.payments.onchain.provider import OnchainProvider

    # Tests default to PAYMENT_PROVIDER=mock, which never looks at on-chain rails at all —
    # force the real on-chain provider so this test actually exercises the reported path.
    monkeypatch.setattr("app.services.orders.get_payment_provider", lambda: OnchainProvider())
    set_rails_override("[]")  # 0 of N rails saved — the exact state the owner hit

    await _accept_terms(client)

    # 11 attempts is one past the 10/hour order_guard limit. Every single one must still
    # report the real, actionable problem — none of them may burn down into rate_limited.
    for attempt in range(11):
        r = await client.post("/api/twa/orders", json={"tariff_code": "daily"})
        assert r.status_code == 503, f"attempt {attempt}: {r.status_code} {r.text}"
        body = r.json()
        assert body["error"]["code"] == "payments_unconfigured"
        assert "administrator" in body["error"]["message"]
        assert "Wallets" in body["error"]["message"]

    # Free trial never needs a wallet — it must still go through untouched.
    trial = await client.post("/api/twa/orders", json={"tariff_code": "trial"})
    assert trial.status_code == 200, trial.text
    assert trial.json()["order"]["status"] == "completed"


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


async def test_wallet_handoff_redirects_into_the_scheme(client: AsyncClient, engine) -> None:
    """`/pay/{order}` is the only way a Telegram mini app can reach a wallet at all.

    The client's WebView cannot navigate to `ethereum:` — it aborts the page with
    ERR_UNKNOWN_URL_SCHEME and the buyer loses the checkout screen mid-payment. Telegram
    will open an https URL in the real browser, and the real browser hands the scheme to
    the OS, so the hand-off has to be a redirect and not a rendered page.
    """
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from app.models import Invoice, Order, Tariff, User
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        user = (await s.execute(select(User).limit(1))).scalars().first()
        tariff = (await s.execute(select(Tariff).where(Tariff.code == "daily"))).scalars().first()
        order = Order(
            user_id=user.id, tariff_id=tariff.id, tariff_code="daily",
            amount_usd=Decimal("10.00"), status="awaiting_payment",
        )
        s.add(order)
        await s.flush()
        inv = Invoice(
            order_id=order.id, provider="onchain", provider_invoice_id="inv-handoff",
            status="pending", amount_usd=Decimal("10.00"), crypto_currency="ETH",
            crypto_network="native", crypto_amount=Decimal("0.00527902"),
            pay_address="0x26EC39DFf42f1D61A3F40D655178dBCA92A3E0b1",
            chain="ethereum", expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        s.add(inv)
        await s.commit()
        public_id, invoice_id = str(order.public_id), inv.id

    # Driven through the transport rather than the client: httpx insists on parsing a
    # Location header as an absolute URL and rejects `ethereum:…`, which is exactly the
    # header a browser needs here. The strictness is httpx's, not the browser's.
    from httpx import Request

    transport = ASGITransport(app=app)
    resp = await transport.handle_async_request(Request("GET", f"http://t/pay/{public_id}"))
    await resp.aread()
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("ethereum:")

    # A closed invoice must not send anyone money it can no longer settle.
    async with maker() as s:
        closed = await s.get(Invoice, invoice_id)
        closed.status = "expired"
        await s.commit()
    r = await client.get(f"/pay/{public_id}", follow_redirects=False)
    assert r.status_code == 200 and "Invoice is closed" in r.text

    # Garbage and unknown ids get a page a human can read, not a JSON error body.
    for bad in ("not-a-uuid", "00000000-0000-4000-8000-000000000000"):
        r = await client.get(f"/pay/{bad}")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("text/html")


async def test_invoice_view_offers_the_handoff_only_where_a_scheme_exists(
    client: AsyncClient,
) -> None:
    """Tron has no URI standard, so there is nothing to hand off and no button to show."""
    await _accept_terms(client)
    r = await client.post("/api/twa/orders", json={"tariff_code": "daily"})
    assert r.status_code in (200, 201), r.text
    invoice = r.json()["invoice"]
    if invoice is None:
        return  # no on-chain provider configured in this environment
    if invoice["pay_uri"] and ":" in invoice["pay_uri"]:
        assert invoice["pay_open_url"], "a chain with a deep link must expose the hand-off"
        assert invoice["pay_open_url"].endswith(f"/pay/{r.json()['order']['public_id']}")
    else:
        assert invoice["pay_open_url"] is None

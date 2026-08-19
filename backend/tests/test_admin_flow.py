"""Admin API smoke: login/lockout, JWT auth, refresh, RBAC, key endpoints reachable."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest_asyncio
from app.api import deps
from app.core.config import settings
from app.core.redis import redis_client
from app.main import app
from app.models import OnchainDepositLedger
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
    pwd = settings.seed_admin_password
    assert pwd is not None
    r = await c.post(
        "/api/admin/auth/login",
        json={"email": settings.seed_admin_email, "password": pwd.get_secret_value()},
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


async def test_onchain_ledger_endpoints(engine, raw_client: AsyncClient) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        s.add(
            OnchainDepositLedger(
                status="paid", chain="tron", asset="USDT", network="trc20", txid="0xt1",
                to_address="TAddr", amount=Decimal("10.005"), confirmations=20,
                observed_at=datetime.now(UTC),
            )
        )
        s.add(
            OnchainDepositLedger(
                status="unmatched", chain="bitcoin", asset="BTC", network="native", txid="0xb1",
                to_address="bc1q", amount=Decimal("0.5"), confirmations=3,
                observed_at=datetime.now(UTC),
            )
        )
        await s.commit()

    token = await _login(raw_client)
    raw_client.headers["Authorization"] = f"Bearer {token}"

    listing = (await raw_client.get("/api/admin/payments/ledger")).json()
    assert listing["total"] == 2
    assert {row["status"] for row in listing["items"]} == {"paid", "unmatched"}

    filtered = (
        await raw_client.get("/api/admin/payments/ledger", params={"status": "unmatched"})
    ).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["chain"] == "bitcoin"

    summary = (await raw_client.get("/api/admin/payments/ledger/summary")).json()
    assert summary["by_status"]["paid"] == 1
    assert summary["by_status"]["unmatched"] == 1
    assert summary["unmatched_total"] == 1
    assert summary["events_24h"] == 2

    del raw_client.headers["Authorization"]
    assert (await raw_client.get("/api/admin/payments/ledger")).status_code == 401


async def test_ledger_filters_sorting_and_order_id(engine, raw_client: AsyncClient) -> None:
    """The lookups an operator performs on a customer's three-month-old payment.

    Scrolling is not a search, so each of these has to narrow on the server: by coin, by
    the hash or address pasted from a support chat, by date range, and by amount. The
    order id is checked too — it is the only identifier on this screen the customer can
    quote back.
    """
    from app.models import Invoice, Order, Tariff, User
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        user = (await s.execute(select(User).limit(1))).scalars().first()
        tariff = (await s.execute(select(Tariff).limit(1))).scalars().first()
        assert user is not None and tariff is not None

        order = Order(
            user_id=user.id, tariff_id=tariff.id, tariff_code=tariff.code,
            amount_usd=Decimal("30.00"), status="paid",
        )
        s.add(order)
        await s.flush()
        invoice = Invoice(
            order_id=order.id, provider="onchain", provider_invoice_id="inv-ledger-1",
            status="paid", amount_usd=Decimal("30.00"), crypto_currency="USDC",
            crypto_network="spl", crypto_amount=Decimal("30.000123"), pay_address="SolTo",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        s.add(invoice)
        await s.flush()

        # Three rows spread across coins, dates, amounts and counterparties.
        s.add(OnchainDepositLedger(
            status="paid", chain="solana", asset="USDC", network="spl", txid="sig-aaa",
            from_address="PayerAlpha", to_address="SolTo", amount=Decimal("30.000123"),
            confirmations=1, invoice_id=invoice.id, user_id=user.id,
            observed_at=datetime.now(UTC), created_at=datetime(2026, 3, 14, 12, 0, tzinfo=UTC),
        ))
        s.add(OnchainDepositLedger(
            status="unmatched", chain="tron", asset="USDT", network="trc20", txid="hash-bbb",
            from_address="PayerBeta", to_address="TronTo", amount=Decimal("5.5"),
            confirmations=25, observed_at=datetime.now(UTC),
            created_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
        ))
        s.add(OnchainDepositLedger(
            status="paid", chain="solana", asset="SOL", network="native", txid="sig-ccc",
            from_address="PayerGamma", to_address="SolTo", amount=Decimal("1.25"),
            confirmations=1, observed_at=datetime.now(UTC),
            created_at=datetime(2026, 6, 20, 9, 0, tzinfo=UTC),
        ))
        await s.commit()

    token = await _login(raw_client)
    raw_client.headers["Authorization"] = f"Bearer {token}"
    base = "/api/admin/payments/ledger"

    async def rows(**params):
        return (await raw_client.get(base, params=params)).json()["items"]

    # by coin — SOL and USDC are both on Solana, so the chain filter cannot do this
    assert [r["txid"] for r in await rows(asset="USDC")] == ["sig-aaa"]

    # free-text hits the hash and either address, which is what gets pasted from a chat
    assert [r["txid"] for r in await rows(q="hash-bbb")] == ["hash-bbb"]
    assert [r["txid"] for r in await rows(q="PayerGamma")] == ["sig-ccc"]
    assert {r["txid"] for r in await rows(q="SolTo")} == {"sig-aaa", "sig-ccc"}

    # the same box also takes a coin or a chain name, matched by equality. This is what an
    # operator types first, and before it existed such a query fell through to the substring
    # branch, matched no hash or address, and returned the unfiltered table — which reads as
    # an answer. Case is irrelevant; the frontend no longer withholds short queries either.
    assert [r["txid"] for r in await rows(q="SOL")] == ["sig-ccc"]
    assert [r["txid"] for r in await rows(q="usdc")] == ["sig-aaa"]
    assert [r["txid"] for r in await rows(q="tron")] == ["hash-bbb"]
    assert {r["txid"] for r in await rows(q="solana")} == {"sig-aaa", "sig-ccc"}
    # a coin with no deposits yet must come back empty, never "everything"
    assert await rows(q="BTC") == []

    # date range, end-inclusive: "to 1 June" must include the 1st, not stop before it
    march_only = await rows(since="2026-03-01", before="2026-03-31")
    assert [r["txid"] for r in march_only] == ["sig-aaa"]
    assert [r["txid"] for r in await rows(since="2026-06-01", before="2026-06-01")] == ["hash-bbb"]

    # sorting runs over the whole set, not the page the browser happens to hold
    assert [r["txid"] for r in await rows(sort="amount", order="asc")][0] == "sig-ccc"
    assert [r["txid"] for r in await rows(sort="amount", order="desc")][0] == "sig-aaa"
    assert [r["txid"] for r in await rows(sort="created_at", order="asc")][0] == "sig-aaa"

    # the order id the buyer quotes, resolved through the invoice
    matched = (await rows(q="sig-aaa"))[0]
    assert matched["order_public_id"] == str(order.public_id)
    assert (await rows(q="hash-bbb"))[0]["order_public_id"] is None

    # a malformed date must not be dropped in silence — an unfiltered list reads as an answer
    assert (await raw_client.get(base, params={"since": "14.03.2026"})).status_code == 422


async def test_referral_commission_is_settable_from_admin(raw_client: AsyncClient) -> None:
    """PATCH /settings/referral must actually persist — and be operator-editable."""
    token = await _login(raw_client)
    raw_client.headers["Authorization"] = f"Bearer {token}"

    before = (await raw_client.get("/api/admin/settings/referral")).json()
    assert "referral_pct" in before

    saved = await raw_client.patch(
        "/api/admin/settings/referral",
        json={"referral_pct": 12.5, "referral_min_payout_usd": 30, "referral_hold_days": 7},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["referral_pct"] == 12.5

    # round-trip: a fresh read returns the stored value, not the default
    after = (await raw_client.get("/api/admin/settings/referral")).json()
    assert after["referral_pct"] == 12.5
    assert after["referral_min_payout_usd"] == 30
    assert after["referral_hold_days"] == 7

    # unknown keys (the old frontend contract) must not silently look like a success
    stale = await raw_client.patch(
        "/api/admin/settings/referral", json={"commission_pct": 99}
    )
    assert stale.status_code == 422, stale.text
    assert (await raw_client.get("/api/admin/settings/referral")).json()["referral_pct"] == 12.5


async def test_refresh_rotation_is_single_use(raw_client: AsyncClient) -> None:
    """A refresh token is burned on use and on logout — a captured copy can't be replayed."""
    await _login(raw_client)
    captured = raw_client.cookies.get("bm_refresh")
    assert captured

    # rotating once invalidates the token just used
    assert (await raw_client.post("/api/admin/auth/refresh")).status_code == 200
    replay = await raw_client.post("/api/admin/auth/refresh", cookies={"bm_refresh": captured})
    assert replay.status_code == 401  # old refresh token can't mint another session

    # and logout invalidates the current one too
    current = raw_client.cookies.get("bm_refresh")
    assert (await raw_client.post("/api/admin/auth/logout")).status_code == 200
    after = await raw_client.post("/api/admin/auth/refresh", cookies={"bm_refresh": current})
    assert after.status_code == 401


async def test_no_role_tier_left(engine, raw_client: AsyncClient) -> None:
    """Signing in is the whole authorisation model — an 'operator' can reach everything.

    This used to assert the opposite: a refund over $200 was 403 for anyone but an owner,
    and settings/terms/admins were owner-only. Removed on the client's instruction, so the
    test now guards the removal — a reintroduced gate would fail here rather than surface
    as a 403 in someone's face mid-shift.
    """
    from app.core.security import hash_password
    from app.models import AdminUser
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        s.add(
            AdminUser(
                email="operator@test.local", display_name="Op", role="operator",
                password_hash=hash_password("op-pw-123456"), is_active=True,
            )
        )
        await s.commit()

    login = await raw_client.post(
        "/api/admin/auth/login",
        json={"email": "operator@test.local", "password": "op-pw-123456"},
    )
    assert login.status_code == 200
    raw_client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    # A five-thousand-dollar refund gets as far as any other: 404, because that order does
    # not exist. Not 403.
    fake = "00000000-0000-0000-0000-000000000000"
    big = await raw_client.post(
        f"/api/admin/orders/{fake}/refund", json={"amount_usd": 5000, "reason": "x"}
    )
    assert big.status_code == 404, big.text

    # …and the four screens that were owner-only all answer.
    for path in ("/api/admin/settings", "/api/admin/terms", "/api/admin/admins"):
        r = await raw_client.get(path)
        assert r.status_code == 200, f"{path} → {r.status_code} {r.text[:200]}"


async def test_sync_now_also_walks_external_holds(raw_client: AsyncClient, monkeypatch) -> None:
    """The button's whole promise is "match iproxy right now" — holds included.

    It used to run sync_pool alone, so a phone freed in the iproxy console stayed
    "Held in iproxy" for up to five minutes until the worker cron's own walk reached
    it. The client pressed the button and, correctly, reported it as doing nothing.
    """
    from app.api.admin import domain as admin_domain

    called = {"pool": 0, "holds": 0}

    async def fake_pool(session):
        called["pool"] += 1
        return {"connections": 0}

    async def fake_holds(session):
        called["holds"] += 1
        return {"checked": 7, "held": 0}

    import app.services.provisioning.sync as sync_mod

    monkeypatch.setattr(sync_mod, "sync_pool", fake_pool)
    monkeypatch.setattr(sync_mod, "sync_external_holds", fake_holds)
    monkeypatch.setattr(settings, "feature_real_provisioning", True)

    token = await _login(raw_client)
    r = await raw_client.post(
        "/api/admin/connections/sync", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert called == {"pool": 1, "holds": 1}
    assert body["holds"] == {"checked": 7, "held": 0}

"""The payout history behind the Referrals screen's second tab.

The console could always see the payout *queue* — the two states that still need an
operator. What it could not do was answer the client's actual question: who has taken
money out, when, to which wallet, in which coin, and how much has left in total. The
ledger tab next to this one lists commissions, which is a different question: a commission
is money earned, a payout is money gone.

So the list carries the coin (a payout row stores only its network), the moment it was
settled, and two sums — because "how much have we paid out" and "how much is on this
screen" stop being the same number the moment a rejected request is in view.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest_asyncio
from app.api import deps
from app.core.config import settings
from app.core.redis import redis_client
from app.main import app
from app.models import Payout, User
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
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield c, maker
    app.dependency_overrides.clear()


async def _seed_payouts(maker) -> None:
    async with maker() as s:
        alice = User(tg_user_id=990_101, tg_username="alice", referral_code="HISTA")
        bob = User(tg_user_id=990_102, tg_username="bob", referral_code="HISTB")
        s.add_all([alice, bob])
        await s.flush()
        s.add_all([
            Payout(
                referrer_user_id=alice.id, amount_usd="5.29", wallet_address="TMtvQ" + "1" * 29,
                network="trc20", status="paid", tx_hash="0xabc",
                requested_at=datetime(2026, 9, 4, 9, 0, tzinfo=UTC),
                processed_at=datetime(2026, 9, 4, 9, 43, tzinfo=UTC),
            ),
            Payout(
                referrer_user_id=bob.id, amount_usd="10.58", wallet_address="0x" + "b" * 40,
                network="bep20", status="paid", tx_hash="0xdef",
                requested_at=datetime(2026, 9, 8, 8, 0, tzinfo=UTC),
                processed_at=datetime(2026, 9, 8, 8, 25, tzinfo=UTC),
            ),
            # Asked for and refused: money that never left. In view, but not in "paid".
            Payout(
                referrer_user_id=bob.id, amount_usd="99", wallet_address="0x" + "c" * 40,
                network="erc20", status="rejected",
                requested_at=datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
            ),
        ])
        await s.commit()


async def test_history_lists_every_payout_newest_first(ctx) -> None:
    client, maker = ctx
    await _seed_payouts(maker)

    r = await client.get("/api/admin/payouts", params={"status": "all"})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["total"] == 3
    assert [i["amount_usd"] for i in body["items"]] == [99.0, 10.58, 5.29]
    assert [i["status"] for i in body["items"]] == ["rejected", "paid", "paid"]


async def test_a_settled_payout_carries_its_coin_and_the_moment_it_left(ctx) -> None:
    """Everything the client reads off a row: who, when, how much, where, in what."""
    client, maker = ctx
    await _seed_payouts(maker)

    body = (await client.get("/api/admin/payouts", params={"status": "paid"})).json()
    newest = body["items"][0]

    assert newest["referrer"] == "@bob"
    assert newest["amount_usd"] == 10.58
    assert newest["asset"] == "USDT"
    assert newest["rail_label"] == "USDT BEP-20 (BNB Chain)"
    assert newest["wallet_address"] == "0x" + "b" * 40
    assert newest["tx_hash"] == "0xdef"
    # Settled at 08:25, asked for at 08:00 — the history dates it by the former.
    assert newest["processed_at"].startswith("2026-09-08T08:25")
    assert newest["requested_at"].startswith("2026-09-08T08:00")


async def test_an_open_payout_has_no_settled_moment(ctx) -> None:
    client, maker = ctx
    async with maker() as s:
        user = User(tg_user_id=990_103, tg_username="carol", referral_code="HISTC")
        s.add(user)
        await s.flush()
        s.add(Payout(referrer_user_id=user.id, amount_usd="3", wallet_address="T" + "2" * 33,
                     network="trc20", status="requested"))
        await s.commit()

    body = (await client.get("/api/admin/payouts", params={"status": "all"})).json()
    assert body["items"][0]["processed_at"] is None


async def test_the_two_sums_answer_two_different_questions(ctx) -> None:
    """A rejected request is on the screen and must not count as money paid out."""
    client, maker = ctx
    await _seed_payouts(maker)

    everything = (await client.get("/api/admin/payouts", params={"status": "all"})).json()
    assert everything["total_amount_usd"] == 114.87  # 5.29 + 10.58 + 99
    assert everything["paid_amount_usd"] == 15.87  # the 99 was refused

    # Filtered, both sums narrow with the rows — they are about what is on screen.
    sent = (await client.get("/api/admin/payouts", params={"status": "paid"})).json()
    assert sent["total_amount_usd"] == 15.87
    assert sent["paid_amount_usd"] == 15.87

    ranged = (
        await client.get(
            "/api/admin/payouts", params={"status": "all", "since": "2026-09-08"}
        )
    ).json()
    assert ranged["total"] == 2
    assert ranged["total_amount_usd"] == 109.58  # 10.58 + 99
    assert ranged["paid_amount_usd"] == 10.58


async def test_a_network_we_no_longer_serve_does_not_break_the_page(ctx) -> None:
    """History is forever; the rail table is not. An old row still has to render."""
    client, maker = ctx
    async with maker() as s:
        user = User(tg_user_id=990_104, tg_username="dave", referral_code="HISTD")
        s.add(user)
        await s.flush()
        s.add(Payout(referrer_user_id=user.id, amount_usd="1", wallet_address="who-knows",
                     network="doge_legacy", status="paid"))
        await s.commit()

    body = (await client.get("/api/admin/payouts", params={"status": "all"})).json()
    row = body["items"][0]
    assert row["asset"] == ""
    assert row["rail_label"] == "doge_legacy"

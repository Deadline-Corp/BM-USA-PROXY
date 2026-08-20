"""The watcher stops paying for log scans when nobody owes us anything.

The deposit watcher polled every chain every fifteen seconds whether or not a single
invoice was open, and the log scan is the expensive call by an order of magnitude. On this
shop — ten invoices a week, and zero open at the time of measuring — that was essentially
the entire RPC bill spent asking whether money had arrived that nobody had been asked for.

What must not change is the part that handles money: while an invoice is open, and for a
day after it lapses, the chain is scanned exactly as before. A missed deposit is a customer
who paid and got nothing, which is far more expensive than any RPC plan.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import Invoice, Order, Tariff, User
from app.services.payments.onchain import load_config, run_chain_tick
from app.services.payments.onchain.chain_client import IncomingTransfer
from app.services.payments.onchain.config import MethodConfig
from scripts.seed import seed_locations, seed_settings, seed_tariffs
from sqlalchemy import select

ADDR = "TWatchedAddr11111111111111111111111"


class CountingClient:
    """Records how many times the expensive scan was actually asked for."""

    def __init__(self, *, head: int = 1000) -> None:
        self.chain = "tron"
        self._head = head
        self.scans = 0

    async def get_block_height(self) -> int:
        return self._head

    async def scan(
        self, *, from_block: int, to_block: int, methods: Sequence[MethodConfig]
    ) -> list[IncomingTransfer]:
        self.scans += 1
        return []

    async def confirmations(self, txid: str, *, block_number: int | None = None) -> int:
        return 0

    async def aclose(self) -> None:
        return None


def _config():
    return load_config(
        json.dumps([{"asset": "USDT", "network": "trc20", "address": ADDR}]), "{}"
    )


async def _seed(session) -> None:
    await seed_settings(session)
    await seed_tariffs(session)
    await seed_locations(session)
    await session.flush()


async def _invoice(session, *, inv_id: str, status: str, expires_in: timedelta) -> Invoice:
    tariff = await session.scalar(select(Tariff).where(Tariff.code == "daily"))
    user = User(
        tg_user_id=abs(hash(inv_id)) % 9_000_000 + 2000,
        referral_code=inv_id.replace("-", "").upper()[:12],
    )
    session.add(user)
    await session.flush()
    order = Order(
        user_id=user.id, tariff_id=tariff.id, tariff_code="daily",
        duration_minutes=1440, amount_usd="10", status="awaiting_payment",
    )
    session.add(order)
    await session.flush()
    invoice = Invoice(
        order_id=order.id, provider="onchain", provider_invoice_id=inv_id,
        status=status, amount_usd="10", crypto_currency="USDT", crypto_network="trc20",
        crypto_amount=Decimal("10"), pay_address=ADDR, chain="tron",
        amount_tolerance=Decimal("0"), locked_rate=Decimal("1"),
        expires_at=datetime.now(UTC) + expires_in,
    )
    session.add(invoice)
    await session.flush()
    return invoice


async def test_an_idle_chain_is_not_scanned(session) -> None:
    """No invoice has ever been raised on this chain: there is nothing to look for."""
    await _seed(session)
    client = CountingClient()

    await run_chain_tick(session, client, config=_config())

    assert client.scans == 0


async def test_an_idle_tick_still_carries_the_cursor_forward(session) -> None:
    """Otherwise the first real payment arrives behind a backlog of skipped blocks.

    The cursor moves one bounded window per tick, so leaving it parked while the chain ran
    on would make the next genuine deposit wait for the watcher to crawl up to it.
    """
    await _seed(session)
    client = CountingClient(head=5000)

    report = await run_chain_tick(session, client, config=_config())

    assert client.scans == 0
    assert report.to_block == 5000, "the cursor should sit at the head, not behind it"


async def test_an_open_invoice_is_scanned_for(session) -> None:
    """The part that must not change: money owed means the chain is read."""
    await _seed(session)
    await _invoice(session, inv_id="idle-open", status="pending", expires_in=timedelta(hours=1))
    client = CountingClient()

    await run_chain_tick(session, client, config=_config())

    assert client.scans == 1


async def test_a_just_expired_invoice_is_still_scanned_for(session) -> None:
    """Somebody who sends an hour late still sent us money.

    The window closing must not be the moment we stop looking, or a late payment becomes a
    payment nobody can see — the customer is out of pocket and there is no record to settle
    from.
    """
    await _seed(session)
    await _invoice(
        session, inv_id="idle-late", status="expired", expires_in=-timedelta(hours=2)
    )
    client = CountingClient()

    await run_chain_tick(session, client, config=_config())

    assert client.scans == 1


async def test_a_long_dead_invoice_stops_costing_anything(session) -> None:
    """A day later, nobody is sending against that invoice any more."""
    await _seed(session)
    await _invoice(
        session, inv_id="idle-old", status="expired", expires_in=-timedelta(days=3)
    )
    client = CountingClient()

    await run_chain_tick(session, client, config=_config())

    assert client.scans == 0


async def test_a_confirming_deposit_keeps_the_chain_watched(session) -> None:
    """Seen on-chain but not yet final — the tick still has work to do here."""
    await _seed(session)
    await _invoice(
        session, inv_id="idle-conf", status="confirming", expires_in=-timedelta(days=5)
    )
    client = CountingClient()

    await run_chain_tick(session, client, config=_config())

    assert client.scans == 1, "an unfinished deposit outranks the age of its invoice"

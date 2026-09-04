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


async def test_a_cursor_past_the_head_starts_again_from_the_chain(session) -> None:
    """A position the chain will never reach is a chain that is dead with nothing to show.

    Found on production: Solana's cursor sat 42 million slots beyond the head and had not
    moved in nine days, while every tick reported success. `head >= from_block` was simply
    false, so neither the scan nor the skip ran and the cursor was never touched again — a
    payment on that rail would have been missed exactly like the Ethereum one, and for a
    completely different reason.
    """
    from app.models import ChainCursor

    await _seed(session)
    session.add(ChainCursor(chain="tron", last_scanned_block=42_000_000))
    await session.commit()

    client = CountingClient(head=1_000)

    await run_chain_tick(session, client, config=_config(), max_blocks=100)
    await session.commit()

    cursor = await session.get(ChainCursor, "tron")
    assert cursor is not None
    assert cursor.last_scanned_block <= 1_000, "the cursor must come back to the chain"
    assert cursor.last_scanned_block > 0


class RailRecordingClient(CountingClient):
    """Records which rails each scan was actually asked to look at."""

    def __init__(self, *, head: int = 1000) -> None:
        super().__init__(head=head)
        self.rails: list[tuple[str, str]] = []

    async def scan(self, *, from_block, to_block, methods):
        self.scans += 1
        self.rails += [(m.spec.asset, m.spec.network) for m in methods]
        return []


def _two_rail_config():
    """One chain, two rails — the shape that made a USDT buyer pay for a USDC scan."""
    return load_config(
        json.dumps(
            [
                {"asset": "USDT", "network": "trc20", "address": ADDR},
                {"asset": "TRX", "network": "native", "address": ADDR},
            ]
        ),
        "{}",
    )


async def test_only_the_rail_being_paid_on_is_scanned(session) -> None:
    """A buyer paying USDT used to make us walk the chain for every other coin too.

    On Ethereum that meant scanning USDC and native ETH — the latter block by block —
    for invoices that did not exist, so nothing found there could have belonged to anyone.
    """
    await _seed(session)
    await _invoice(session, inv_id="rail-1", status="pending", expires_in=timedelta(hours=1))
    await session.commit()

    client = RailRecordingClient(head=1000)
    await run_chain_tick(session, client, config=_two_rail_config(), max_blocks=100)

    assert client.scans == 1
    assert client.rails == [("USDT", "trc20")], "the untouched rail must not be scanned"


async def test_nothing_open_anywhere_still_skips_the_scan_entirely(session) -> None:
    """The saving that was already there has to survive the narrowing."""
    await _seed(session)
    await session.commit()

    client = RailRecordingClient(head=1000)
    await run_chain_tick(session, client, config=_two_rail_config(), max_blocks=100)

    assert client.scans == 0
    assert client.rails == []


# ── the doorbell: a webhook says "look now", it never says "you were paid" ─
async def test_without_webhooks_the_poll_is_unchanged(session) -> None:
    """Nothing may get quieter until there is something to be quiet in favour of."""
    from app.services.payments.onchain import webhooks

    await _seed(session)
    await _invoice(session, inv_id="hook-a", status="pending", expires_in=timedelta(hours=1))
    await session.commit()

    client = CountingClient(head=1000)
    await run_chain_tick(session, client, config=_config(), max_blocks=100)
    assert client.scans == 1

    assert await webhooks.scan_is_due("tron") is True


async def test_a_live_webhook_quiets_the_poll_until_it_rings(session) -> None:
    """The saving: an open invoice used to buy a scan every fifteen seconds for an hour."""
    from app.services.payments.onchain import webhooks

    await _seed(session)
    await _invoice(session, inv_id="hook-b", status="pending", expires_in=timedelta(hours=1))
    await session.commit()

    await webhooks.ring("tron")  # a delivery arrived: webhooks are alive on this chain
    client = CountingClient(head=1000)

    # Enough budget for one scan to reach the head. The window is only honoured while we
    # are caught up — a backlog no single scan can clear closes it, because otherwise the
    # heartbeat can never catch up. Tron's cursor is in milliseconds and its rescan overlap
    # is five minutes of them, so a small budget here would leave a permanent backlog and
    # this test would be measuring that instead of the webhook.
    await run_chain_tick(session, client, config=_config(), max_blocks=100_000)
    assert client.scans == 1, "the ring must be honoured"

    await run_chain_tick(session, client, config=_config(), max_blocks=100_000)
    await run_chain_tick(session, client, config=_config(), max_blocks=100_000)
    assert client.scans == 1, "and nothing more until it rings again or the heartbeat is due"

    await webhooks.ring("tron")
    await run_chain_tick(session, client, config=_config(), max_blocks=100_000)
    assert client.scans == 2


async def test_waiting_on_a_webhook_never_advances_the_cursor(session) -> None:
    """The bug this nearly shipped as.

    Skipping because a webhook is quiet is not the same as skipping because nothing is
    owed. The idle path carries the cursor to the head, which is right when no invoice
    exists — nothing in those blocks could belong to anybody. With an invoice open the
    blocks going by are exactly the ones the payment may be in, so advancing over them
    would step past the money and never look again.
    """
    from app.models.onchain import ChainCursor
    from app.services.payments.onchain import webhooks

    await _seed(session)
    await _invoice(session, inv_id="hook-c", status="pending", expires_in=timedelta(hours=1))
    await session.commit()

    await webhooks.ring("tron")
    first = CountingClient(head=1000)
    await run_chain_tick(session, first, config=_config(), max_blocks=100_000)
    await session.flush()
    after_scan = await session.get(ChainCursor, "tron")
    assert after_scan is not None
    settled = after_scan.last_scanned_block

    # chain moves on, webhook stays quiet
    later = CountingClient(head=50_000)
    await run_chain_tick(session, later, config=_config(), max_blocks=100_000)
    await session.flush()
    waited = await session.get(ChainCursor, "tron")

    assert later.scans == 0, "quiet webhook — no scan"
    assert waited is not None
    assert waited.last_scanned_block == settled, "the unscanned blocks must still be pending"


async def test_a_delivery_is_only_believed_if_it_is_signed() -> None:
    """The payload is a doorbell, and an unsigned one is somebody rattling the gate."""
    import json as _json

    from app.core.config import settings
    from app.services.payments.onchain import webhooks

    body = _json.dumps({"event": {"network": "ETH_MAINNET"}}).encode()
    original = settings.alchemy_webhook_keys
    try:
        settings.alchemy_webhook_keys = _json.dumps({"ETH_MAINNET": "whsec_test"})
        import hashlib
        import hmac as _hmac

        good = _hmac.new(b"whsec_test", body, hashlib.sha256).hexdigest()

        assert webhooks.verify(body, good) is True
        assert webhooks.verify(body, "deadbeef") is False
        assert webhooks.verify(body, None) is False
        assert webhooks.verify(body + b" ", good) is False, "signed over the raw bytes"
    finally:
        settings.alchemy_webhook_keys = original


def test_only_networks_we_run_on_are_acted_on() -> None:
    """A delivery for a chain we do not watch is dropped rather than guessed at."""
    from app.services.payments.onchain import webhooks

    assert webhooks.chain_of({"event": {"network": "ETH_MAINNET"}}) == "ethereum"
    assert webhooks.chain_of({"event": {"network": "BNB_MAINNET"}}) == "bsc"
    assert webhooks.chain_of({"event": {"network": "MATIC_MAINNET"}}) is None
    assert webhooks.chain_of({"nonsense": True}) is None
    assert webhooks.chain_of("not a dict") is None


# ── the quiet window must not hold up a payment that is already in ────────


class DeepConfirmClient(CountingClient):
    """Answers that the known txid is buried deep, and counts the log scans it was asked for."""

    def __init__(self, *, head: int = 1000) -> None:
        super().__init__(head=head)
        self.confirmation_checks = 0

    async def confirmations(self, txid: str, *, block_number: int | None = None) -> int:
        self.confirmation_checks += 1
        return 999


async def test_the_quiet_window_skips_the_scan_but_never_the_confirmation_check(
    session, monkeypatch
) -> None:
    """What a customer waited five minutes for on 2026-09-04.

    A BEP20 deposit was seen at 9 confirmations against the rail's 15. BSC makes about two
    blocks a second, so the six it still needed took under three seconds — but the chain's
    webhooks were alive, the next tick found the quiet window open and returned before
    reaching `finalize_confirming`, and nothing looked at the depth again until the window
    expired 300 seconds later.

    The two calls cost nothing alike and must not share a gate: the scan sweeps a block
    range for transfers nobody has seen, while this asks the depth of one known txid.
    """
    from app.services.payments.onchain import watcher as watcher_mod
    from app.services.payments.onchain import webhooks as onchain_webhooks

    await _seed(session)
    await _invoice(session, inv_id="quiet-1", status="confirming", expires_in=timedelta(hours=1))
    await session.flush()

    calls = {"finalize": 0}
    real = watcher_mod.finalize_confirming

    async def counting_finalize(*a, **kw):
        calls["finalize"] += 1
        return await real(*a, **kw)

    monkeypatch.setattr(watcher_mod, "finalize_confirming", counting_finalize)

    # Webhooks arriving, nothing ringing, a scan just happened — the quiet window.
    await onchain_webhooks.ring("tron")
    await onchain_webhooks.note_scan("tron")
    assert not await onchain_webhooks.scan_is_due("tron"), "test needs the window actually open"

    client = DeepConfirmClient()
    report = await run_chain_tick(session, client=client, config=_config())

    assert client.scans == 0, "the expensive scan is what the quiet window is for"
    assert calls["finalize"] == 1, "the depth of a deposit already in hand must still be read"
    # The property the early return was protecting: a skipped scan must not step the cursor
    # past blocks the payment could be sitting in.
    assert report.to_block == report.from_block - 1 or report.transfers == 0


class BacklogClient(CountingClient):
    """A chain whose head has run far ahead of where the cursor was left."""

    async def confirmations(self, txid: str, *, block_number: int | None = None) -> int:
        return 999


async def test_the_quiet_window_closes_once_the_backlog_outgrows_one_scan(session) -> None:
    """Otherwise the heartbeat cannot catch up, and the cursor falls behind for good.

    A scan covers `max_blocks`. If the chain produces more than that inside one quiet
    window, every window ends further behind than it started, and there is no later tick
    that recovers — the gap only grows.

    Measured on production 2026-09-04: BSC makes about 650 blocks in the 300-second window
    against a 500-block scan, and the deposit cursor had drifted 9,796 blocks — about eighty
    minutes — behind the head. A customer's USDT sat in a block the scan had not reached.
    The payout watcher on the same chain, which has no quiet window, was at the head.
    """
    from app.services.payments.onchain import webhooks as onchain_webhooks

    await _seed(session)
    await _invoice(session, inv_id="backlog-1", status="pending", expires_in=timedelta(hours=1))
    await session.flush()

    await onchain_webhooks.ring("tron")
    await onchain_webhooks.note_scan("tron")
    assert not await onchain_webhooks.scan_is_due("tron"), "test needs the window open"

    # Caught up: the window is honoured and the expensive call is skipped.
    near = BacklogClient(head=1000)
    await run_chain_tick(session, client=near, config=_config(), max_blocks=500)
    assert near.scans == 0

    # The same open window, but now the head is further off than one scan can reach.
    far = BacklogClient(head=1000 + 900)
    await run_chain_tick(session, client=far, config=_config(), max_blocks=500)
    assert far.scans == 1, "a backlog no single scan can clear must not wait on the window"

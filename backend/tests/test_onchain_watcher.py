"""End-to-end tests for the generic on-chain watcher against a real DB.

A fake ChainClient feeds synthetic transfers through ``run_chain_tick`` and we assert the
whole pipeline: append-only ledger rows, invoice status history, idempotent activation
(exactly one access), and the safe fallbacks (unmatched / ambiguous → parked, not credited).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import Access, Invoice, Order, Tariff, User
from app.models.commerce import PaymentEvent
from app.models.onchain import InvoiceStatusHistory, OnchainDepositLedger
from app.services.payments.onchain import load_config, run_chain_tick
from app.services.payments.onchain.chain_client import IncomingTransfer
from app.services.payments.onchain.config import MethodConfig
from scripts.seed import seed_dev_fixtures, seed_locations, seed_settings, seed_tariffs
from sqlalchemy import func, select

ADDR = "TWatchedAddr11111111111111111111111"


class FakeChainClient:
    """In-memory ChainClient: returns queued transfers on scan, confs from a dict."""

    def __init__(
        self,
        *,
        chain: str,
        head: int,
        scan_rounds: list[list[IncomingTransfer]] | None = None,
        confs: dict[str, int] | None = None,
    ) -> None:
        self.chain = chain
        self._head = head
        self._rounds = list(scan_rounds or [])
        self.confs = dict(confs or {})

    async def get_block_height(self) -> int:
        return self._head

    async def scan(
        self, *, from_block: int, to_block: int, methods: Sequence[MethodConfig]
    ) -> list[IncomingTransfer]:
        return self._rounds.pop(0) if self._rounds else []

    async def confirmations(self, txid: str, *, block_number: int | None = None) -> int:
        return self.confs.get(txid, 0)

    async def aclose(self) -> None:
        return None


def _config(confirmations: int = 19):
    return load_config(
        json.dumps(
            [{"asset": "USDT", "network": "trc20", "address": ADDR, "confirmations": confirmations}]
        ),
        "{}",
    )


def _transfer(txid: str, amount: Decimal, confirmations: int) -> IncomingTransfer:
    return IncomingTransfer(
        chain="tron",
        asset="USDT",
        network="trc20",
        txid=txid,
        to_address=ADDR,
        amount=amount,
        confirmations=confirmations,
    )


async def _seed(session) -> None:
    await seed_settings(session)
    await seed_tariffs(session)
    await seed_locations(session)
    await session.flush()
    await seed_dev_fixtures(session)
    await session.flush()


async def _make_order(
    session, *, inv_id: str, expected: Decimal, amount: str = "10"
) -> tuple[Order, Invoice]:
    tariff = await session.scalar(select(Tariff).where(Tariff.code == "daily"))
    user = User(
        tg_user_id=abs(hash(inv_id)) % 9_000_000 + 1000,
        referral_code=inv_id.replace("-", "").upper()[:12],
    )
    session.add(user)
    await session.flush()
    order = Order(
        user_id=user.id,
        tariff_id=tariff.id,
        tariff_code="daily",
        duration_minutes=1440,
        amount_usd=amount,
        status="awaiting_payment",
    )
    session.add(order)
    await session.flush()
    invoice = Invoice(
        order_id=order.id,
        provider="onchain",
        provider_invoice_id=inv_id,
        status="pending",
        amount_usd=amount,
        crypto_currency="USDT",
        crypto_network="trc20",
        crypto_amount=expected,
        pay_address=ADDR,
        chain="tron",
        amount_tolerance=Decimal("0"),
        locked_rate=Decimal("1"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(invoice)
    await session.flush()
    return order, invoice


async def _access_count(session, order_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(Access).where(Access.order_id == order_id)
        )
        or 0
    )


async def _ledger_statuses(session, txid: str) -> set[str]:
    rows = await session.scalars(
        select(OnchainDepositLedger.status).where(OnchainDepositLedger.txid == txid)
    )
    return set(rows)


async def _latest_ledger_status(session, txid: str) -> str | None:
    return await session.scalar(
        select(OnchainDepositLedger.status)
        .where(OnchainDepositLedger.txid == txid)
        .order_by(OnchainDepositLedger.created_at.desc(), OnchainDepositLedger.id.desc())
        .limit(1)
    )


async def _history(session, invoice_id: int) -> list[tuple[str | None, str]]:
    rows = await session.execute(
        select(InvoiceStatusHistory.from_status, InvoiceStatusHistory.to_status)
        .where(InvoiceStatusHistory.invoice_id == invoice_id)
        .order_by(InvoiceStatusHistory.id)
    )
    return [(r[0], r[1]) for r in rows]


async def _onchain_event_count(session) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(PaymentEvent).where(PaymentEvent.provider == "onchain")
        )
        or 0
    )


async def test_full_pipeline_one_tick(session) -> None:
    await _seed(session)
    expected = Decimal("10.005000")
    order, invoice = await _make_order(session, inv_id="oc-1", expected=expected)
    client = FakeChainClient(
        chain="tron", head=1000, scan_rounds=[[_transfer("0xdep1", expected, 20)]]
    )

    report = await run_chain_tick(session, client, config=_config())

    assert report.transfers == 1
    await session.refresh(invoice)
    await session.refresh(order)
    assert invoice.status == "paid"
    assert order.status == "completed"
    assert await _access_count(session, order.id) == 1
    assert invoice.matched_txid == "0xdep1"

    statuses = await _ledger_statuses(session, "0xdep1")
    assert "detected" in statuses
    assert "paid" in statuses
    assert await _latest_ledger_status(session, "0xdep1") == "paid"

    history = await _history(session, invoice.id)
    assert ("pending", "confirming") in history
    assert ("confirming", "paid") in history
    assert await _onchain_event_count(session) == 1


async def test_confirming_then_finalized_next_tick(session) -> None:
    await _seed(session)
    expected = Decimal("10.005000")
    order, invoice = await _make_order(session, inv_id="oc-2", expected=expected)
    client = FakeChainClient(
        chain="tron",
        head=1000,
        scan_rounds=[[_transfer("0xdep2", expected, 1)]],
        confs={"0xdep2": 1},
    )

    await run_chain_tick(session, client, config=_config())
    await session.refresh(invoice)
    assert invoice.status == "confirming"
    assert await _access_count(session, order.id) == 0

    # confirmations deepen → straggler finalizes on the next tick (no new blocks scanned)
    client.confs["0xdep2"] = 25
    report = await run_chain_tick(session, client, config=_config())
    await session.refresh(invoice)
    await session.refresh(order)
    assert invoice.status == "paid"
    assert report.finalized == 1
    assert await _access_count(session, order.id) == 1


async def test_overpayment_still_activates(session) -> None:
    await _seed(session)
    expected = Decimal("10.005000")
    order, invoice = await _make_order(session, inv_id="oc-3", expected=expected)
    client = FakeChainClient(
        chain="tron", head=1000, scan_rounds=[[_transfer("0xdep3", Decimal("10.010000"), 20)]]
    )

    await run_chain_tick(session, client, config=_config())
    await session.refresh(invoice)
    assert invoice.status == "paid"
    assert await _access_count(session, order.id) == 1
    assert await _latest_ledger_status(session, "0xdep3") == "overpaid"


async def test_unmatched_deposit_is_parked(session) -> None:
    await _seed(session)
    order, invoice = await _make_order(session, inv_id="oc-4", expected=Decimal("10.005000"))
    client = FakeChainClient(
        chain="tron", head=1000, scan_rounds=[[_transfer("0xdep4", Decimal("3.000000"), 20)]]
    )

    await run_chain_tick(session, client, config=_config())
    await session.refresh(invoice)
    assert invoice.status == "pending"  # untouched
    assert await _access_count(session, order.id) == 0
    assert await _latest_ledger_status(session, "0xdep4") == "unmatched"


async def test_ambiguous_amount_not_credited(session) -> None:
    await _seed(session)
    expected = Decimal("10.005000")
    order1, inv1 = await _make_order(session, inv_id="oc-5a", expected=expected)
    order2, inv2 = await _make_order(session, inv_id="oc-5b", expected=expected)
    client = FakeChainClient(
        chain="tron", head=1000, scan_rounds=[[_transfer("0xdep5", expected, 20)]]
    )

    await run_chain_tick(session, client, config=_config())
    await session.refresh(inv1)
    await session.refresh(inv2)
    assert inv1.status == "pending"
    assert inv2.status == "pending"
    assert await _access_count(session, order1.id) == 0
    assert await _access_count(session, order2.id) == 0
    assert await _latest_ledger_status(session, "0xdep5") == "unmatched"

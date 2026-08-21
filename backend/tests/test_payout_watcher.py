"""Payout auto-confirmation: our outgoing USDT transfer closes the matching payout."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from app.models import AdminUser, Order, Payout, ReferralLedger, Tariff, User
from app.models.onchain import OnchainDepositLedger
from app.services.payments.onchain.assets import USDT_TRC20
from app.services.payments.onchain.chain_client import IncomingTransfer
from app.services.payments.onchain.config import load_config
from app.services.payments.onchain.payout_watcher import process_outgoing, run_payout_tick
from sqlalchemy import select

SRC = "TPayoutSrcAddr11111111111111111111"
DEST = "TRecipientAddr2222222222222222222"


def _config():
    return load_config(
        "[]", "{}", "mainnet",
        json.dumps([{"network": "trc20", "address": SRC}]),
    )


def _transfer(txid: str, amount: str, to_address: str = DEST) -> IncomingTransfer:
    return IncomingTransfer(
        chain="tron", asset="USDT", network="trc20", txid=txid,
        to_address=to_address, amount=Decimal(amount), from_address=SRC, confirmations=25,
    )


async def _payout(session, *, amount: str, address: str = DEST, status: str = "approved") -> Payout:
    seq = abs(hash(amount + address))
    admin = AdminUser(email=f"op-{seq % 10**8}@t.local", display_name="Op",
                      role="operator", password_hash="x")
    referrer = User(tg_user_id=seq % 9_000_000 + 7_000_000, referral_code=f"PO{seq % 100000:05d}")
    referee = User(tg_user_id=seq % 9_000_000 + 8_000_000, referral_code=f"PE{seq % 100000:05d}")
    tariff = await session.scalar(select(Tariff).where(Tariff.code == "daily"))
    if tariff is None:
        tariff = Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                        price_usd="10")
        session.add(tariff)
    session.add_all([admin, referrer, referee])
    await session.flush()

    # a real paid order — referral_ledger.order_id is NOT NULL, and the backing sum is what
    # mark_payout_paid checks before releasing a payout
    order = Order(user_id=referee.id, tariff_id=tariff.id, tariff_code="daily",
                  amount_usd=amount, status="completed", referrer_user_id=referrer.id,
                  paid_at=datetime.now(UTC))
    session.add(order)
    await session.flush()

    payout = Payout(referrer_user_id=referrer.id, amount_usd=amount, wallet_address=address,
                    network="trc20", status=status, operator_id=admin.id)
    session.add(payout)
    await session.flush()
    session.add(ReferralLedger(referrer_user_id=referrer.id, referee_user_id=referee.id,
                               order_id=order.id, kind="accrual", base_amount_usd=amount,
                               pct=23, amount_usd=amount, status="requested",
                               payout_id=payout.id))
    await session.flush()
    return payout


async def _ledger_rows(session, txid: str) -> list[OnchainDepositLedger]:
    return list(await session.scalars(
        select(OnchainDepositLedger).where(OnchainDepositLedger.txid == txid)
    ))


async def test_outgoing_transfer_confirms_payout(session) -> None:
    payout = await _payout(session, amount="47.00")
    assert await process_outgoing(session, _transfer("0xout1", "47.00")) is True

    await session.refresh(payout)
    assert payout.status == "paid"
    assert payout.tx_hash == "0xout1"  # the real on-chain txid, not hand-typed
    rows = await _ledger_rows(session, "0xout1")
    assert len(rows) == 1
    assert rows[0].direction == "out" and rows[0].status == "paid"
    assert rows[0].payout_id == payout.id


async def test_same_transfer_processed_once(session) -> None:
    payout = await _payout(session, amount="12.50")
    assert await process_outgoing(session, _transfer("0xout2", "12.50")) is True
    # replay (next tick sees the same tx) → no second confirmation, no duplicate ledger row
    assert await process_outgoing(session, _transfer("0xout2", "12.50")) is False
    assert len(await _ledger_rows(session, "0xout2")) == 1
    await session.refresh(payout)
    assert payout.status == "paid"


async def test_wrong_amount_is_not_confirmed(session) -> None:
    payout = await _payout(session, amount="47.00")
    assert await process_outgoing(session, _transfer("0xout3", "40.00")) is False
    await session.refresh(payout)
    assert payout.status == "approved"  # untouched
    rows = await _ledger_rows(session, "0xout3")
    assert rows[0].status == "unmatched"
    assert "amount does not match" in rows[0].meta["reason"]


async def test_unknown_recipient_is_not_confirmed(session) -> None:
    await _payout(session, amount="47.00")
    assert await process_outgoing(session, _transfer("0xout4", "47.00", to_address="TStranger9")) is False
    rows = await _ledger_rows(session, "0xout4")
    assert rows[0].status == "unmatched"
    assert "no open payout" in rows[0].meta["reason"]


async def test_payout_nobody_approved_is_not_confirmed(session) -> None:
    """A transfer must not close a payout that was never authorised.

    Approve and Send are one button in the admin now, so anything sendable has been
    approved by the time an operator can see the transfer instructions. If the watcher
    also settled 'requested' payouts, that authorisation would be optional in practice:
    the person holding the wallet could move the money and have the system file it as
    paid with nobody's name against the decision.
    """
    payout = await _payout(session, amount="15.00", status="requested")
    assert await process_outgoing(session, _transfer("0xout-unapproved", "15.00")) is False

    await session.refresh(payout)
    assert payout.status == "requested"  # untouched — still waiting on a human
    rows = await _ledger_rows(session, "0xout-unapproved")
    assert rows[0].status == "unmatched"  # recorded, not silently dropped


async def test_ambiguous_payouts_are_not_confirmed(session) -> None:
    # two identical open payouts to the same address — a machine must not guess
    p1 = await _payout(session, amount="25.00")
    p2 = Payout(referrer_user_id=p1.referrer_user_id, amount_usd="25.00",
                wallet_address=DEST, network="trc20", status="approved")
    session.add(p2)
    await session.flush()

    assert await process_outgoing(session, _transfer("0xout5", "25.00")) is False
    await session.refresh(p1)
    assert p1.status == "approved"
    rows = await _ledger_rows(session, "0xout5")
    assert rows[0].status == "unmatched"
    assert "ambiguous" in rows[0].meta["reason"]


async def test_open_queue_includes_approved(session) -> None:
    """An approved payout must stay in the queue — 'send' happens after approve."""
    from app.api.admin.domain import list_payouts

    requested = await _payout(
        session, amount="10.00", address="TReqAddr1111111111111111111111", status="requested"
    )
    approved = await _payout(
        session, amount="20.00", address="TAppAddr2222222222222222222222", status="approved"
    )
    paid = await _payout(
        session, amount="30.00", address="TPaidAddr333333333333333333333", status="paid"
    )

    open_queue = await list_payouts(admin=None, session=session)  # type: ignore[arg-type]
    ids = {row["id"] for row in open_queue["items"]}
    assert str(requested.id) in ids
    assert str(approved.id) in ids   # regression: used to be filtered out
    assert str(paid.id) not in ids

    # an explicit status still filters exactly
    only_paid = await list_payouts(admin=None, session=session, status="paid")  # type: ignore[arg-type]
    assert {row["id"] for row in only_paid["items"]} == {str(paid.id)}


async def test_payout_instruction_prefills_everything(session) -> None:
    """The operator must not retype an address or an amount — both come from the API."""
    from app.api.admin.domain import payout_instruction
    from app.services.payments.onchain.assets import USDT_BEP20

    tron_payout = await _payout(session, amount="47.00")
    inst = await payout_instruction(tron_payout.id, admin=None, session=session)  # type: ignore[arg-type]
    assert inst["network"] == "trc20"
    assert inst["to_address"] == DEST
    assert inst["amount"] == "47.00"
    assert inst["token_contract"] == USDT_TRC20
    assert inst["wallet_uri"] is None          # Tron has no EIP-681 equivalent
    assert inst["qr_payload"] == DEST          # …so the QR carries the address itself

    evm = await _payout(session, amount="12.50", address="0x" + "a" * 40)
    evm.network = "bep20"
    await session.flush()
    inst = await payout_instruction(evm.id, admin=None, session=session)  # type: ignore[arg-type]
    # EIP-681 with the amount in base units (12.50 USDT-BEP20, 18 decimals)
    assert inst["wallet_uri"] == (
        f"ethereum:{USDT_BEP20}@56/transfer"
        f"?address=0x{'a' * 40}&uint256={125 * 10**17}"
    )
    assert inst["qr_payload"] == inst["wallet_uri"]


class FakeOutgoingClient:
    chain = "tron"

    def __init__(self, head: int, transfers: list[IncomingTransfer]) -> None:
        self._head = head
        self._transfers = transfers
        self.calls: list[dict] = []

    async def get_block_height(self) -> int:
        return self._head

    async def scan_outgoing(self, **kwargs) -> list[IncomingTransfer]:
        self.calls.append(kwargs)
        return self._transfers

    async def aclose(self) -> None:
        return None


async def test_tick_scans_configured_source_and_advances_cursor(session) -> None:
    payout = await _payout(session, amount="9.99")
    client = FakeOutgoingClient(1_700_000_000_000, [_transfer("0xtick", "9.99")])

    confirmed = await run_payout_tick(session, client, _config())

    assert confirmed == 1
    await session.refresh(payout)
    assert payout.status == "paid"
    # scanned our configured payout wallet, for the right token contract
    assert client.calls[0]["source_address"] == SRC
    assert client.calls[0]["token_contract"] == USDT_TRC20
    # a second tick with no new transfers is a no-op
    client._transfers = []
    assert await run_payout_tick(session, client, _config()) == 0


# ── the scan costs money, so it must not run when it cannot find anything ─
async def test_no_approved_payout_means_no_log_scan(session) -> None:
    """This tick ran twice a minute on three chains and never once asked whether it could
    find anything.

    Measured on production: one payout has ever been made and it was confirmed long ago, so
    every scan since was looking for a transfer that cannot exist. On a plan billed by the
    call, that is the plan running out — which is exactly what happened, and it took the
    deposit watcher down with it on the same key.
    """
    await _payout(session, amount="9.99", status="paid")  # settled, nothing to look for
    client = FakeOutgoingClient(1_700_000_000_000, [_transfer("0xnope", "9.99")])

    confirmed = await run_payout_tick(session, client, _config())

    assert confirmed == 0
    assert client.calls == [], "nothing approved — the expensive scan must not be made"


async def test_an_approved_payout_still_gets_scanned_for(session) -> None:
    """The other half: the moment there is something to confirm, the scan happens."""
    payout = await _payout(session, amount="9.99", status="approved")
    client = FakeOutgoingClient(1_700_000_000_000, [_transfer("0xyes", "9.99")])

    confirmed = await run_payout_tick(session, client, _config())

    assert confirmed == 1
    assert client.calls, "an approved payout must still be looked for"
    await session.refresh(payout)
    assert payout.status == "paid"


async def test_an_idle_tick_still_carries_the_cursor_forward(session) -> None:
    """Otherwise the saving becomes a debt: the cursor stands still while the chain moves,
    and the next real payout pays for every block that went by in between."""
    from app.models.onchain import ChainCursor

    await _payout(session, amount="9.99", status="paid")
    early = FakeOutgoingClient(1_700_000_000_000, [])
    await run_payout_tick(session, early, _config())
    await session.flush()
    first = await session.get(ChainCursor, "tron:payout")
    assert first is not None
    started_at = first.last_scanned_block

    later = FakeOutgoingClient(1_700_000_600_000, [])  # ten minutes of chain later
    await run_payout_tick(session, later, _config())
    await session.flush()
    moved = await session.get(ChainCursor, "tron:payout")

    assert moved is not None
    assert moved.last_scanned_block > started_at, "an idle tick must not let a backlog form"

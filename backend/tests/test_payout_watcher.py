"""Payout auto-confirmation: our outgoing USDT transfer closes the matching payout."""

from __future__ import annotations

import json
from decimal import Decimal

from app.models import AdminUser, Payout, ReferralLedger, User
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
    admin = AdminUser(email=f"op-{amount}-{address[:6]}@t.local", display_name="Op",
                      role="operator", password_hash="x")
    user = User(tg_user_id=abs(hash(amount + address)) % 9_000_000 + 7000,
                referral_code=f"PO{abs(hash(address)) % 100000:05d}")
    session.add_all([admin, user])
    await session.flush()
    payout = Payout(referrer_user_id=user.id, amount_usd=amount, wallet_address=address,
                    network="trc20", status=status, operator_id=admin.id)
    session.add(payout)
    await session.flush()
    # backing ledger row — mark_payout_paid refuses a payout its ledger doesn't back
    session.add(ReferralLedger(referrer_user_id=user.id, referee_user_id=user.id, kind="accrual",
                               base_amount_usd=amount, pct=23, amount_usd=amount,
                               status="requested", payout_id=payout.id))
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

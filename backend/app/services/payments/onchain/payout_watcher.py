"""Auto-confirmation of referral payouts (Variant 1 of the payout design).

A human sends the USDT from our payout wallet; this watcher recognises that outgoing
transfer on-chain and closes the payout itself — attaching the **real** txid from the
blockchain instead of a hand-typed one, and flagging anything that doesn't line up.

The backend stays watch-only: it knows the public address we send from, never a key.

Matching is intentionally strict — an outgoing transfer settles a payout only when the
recipient address, the network and the amount all agree, and only when exactly one payout
matches. Anything else is recorded as ``unmatched`` for a human to look at, because
silently attaching a payment to the wrong payout is worse than not attaching it at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.models import Payout
from app.models.onchain import ChainCursor, OnchainDepositLedger
from app.services import referral
from app.services.payments.onchain.chain_client import IncomingTransfer
from app.services.payments.onchain.config import OnchainConfig, PayoutSource
from app.services.payouts import PAYOUT_RAILS

# payout cursors live under a separate key so they never collide with deposit cursors
_CURSOR_SUFFIX = ":payout"

# how far back a fresh cursor starts (Tron cursor = ms, EVM = blocks)
_TRON_BACKFILL_MS = 30 * 60 * 1000
_EVM_BACKFILL_BLOCKS = 200

# Approved only. A 'requested' payout is one nobody has authorised yet, and settling it
# would mean an outgoing transfer that merely matches an address and an amount could close
# a request on its own — the approval step would be decorative, skippable by the very
# person holding the wallet. The admin's Send button approves and then shows the transfer
# instructions, so by the time anyone can send, the payout is approved.
_OPEN_PAYOUT_STATUSES = ("approved",)


@runtime_checkable
class OutgoingCapableClient(Protocol):
    """A chain client that can list transfers sent FROM one of our wallets."""

    chain: str

    async def get_block_height(self) -> int: ...

    async def scan_outgoing(
        self, *, from_block: int, to_block: int, source_address: str, token_contract: str,
        decimals: int = 6, asset: str = "USDT", network: str = "erc20",
    ) -> list[IncomingTransfer]: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _cursor(session: AsyncSession, chain: str, head: int, backfill: int) -> ChainCursor:
    key = f"{chain}{_CURSOR_SUFFIX}"
    cursor = await session.get(ChainCursor, key)
    if cursor is None:
        cursor = ChainCursor(chain=key, last_scanned_block=max(0, head - backfill))
        session.add(cursor)
        await session.flush()
    return cursor


async def _already_recorded(session: AsyncSession, transfer: IncomingTransfer) -> bool:
    """An outgoing transfer is processed once — keyed by (txid, log_index, direction)."""
    found = await session.scalar(
        select(OnchainDepositLedger.id)
        .where(
            OnchainDepositLedger.direction == "out",
            OnchainDepositLedger.txid == transfer.txid,
            OnchainDepositLedger.log_index == transfer.log_index,
        )
        .limit(1)
    )
    return found is not None


async def _record(
    session: AsyncSession,
    transfer: IncomingTransfer,
    status: str,
    *,
    payout_id: int | None = None,
    user_id: int | None = None,
    meta: dict | None = None,
) -> None:
    session.add(
        OnchainDepositLedger(
            direction="out",
            status=status,
            chain=transfer.chain,
            asset=transfer.asset,
            network=transfer.network,
            txid=transfer.txid,
            log_index=transfer.log_index,
            from_address=transfer.from_address,
            to_address=transfer.to_address,
            amount=transfer.amount,
            amount_usd=transfer.amount,  # USDT — 1:1 with USD
            confirmations=transfer.confirmations,
            block_number=transfer.block_number,
            block_time=transfer.block_time,
            observed_at=_utcnow(),
            payout_id=payout_id,
            user_id=user_id,
            meta=meta or {},
        )
    )
    await session.flush()


async def _match_payout(
    session: AsyncSession, transfer: IncomingTransfer
) -> tuple[Payout | None, str]:
    """Find the single open payout this outgoing transfer settles."""
    candidates = list(
        await session.scalars(
            select(Payout).where(
                Payout.status.in_(_OPEN_PAYOUT_STATUSES),
                Payout.network == transfer.network,
            )
        )
    )
    target = transfer.to_address.strip().lower()
    same_address = [p for p in candidates if p.wallet_address.strip().lower() == target]
    if not same_address:
        return None, "no open payout for this address"

    sent = Decimal(str(transfer.amount)).quantize(Decimal("0.01"))
    exact = [p for p in same_address if Decimal(str(p.amount_usd)).quantize(Decimal("0.01")) == sent]
    if len(exact) == 1:
        return exact[0], "exact"
    if len(exact) > 1:
        # two identical open payouts to one address — a human must say which one
        return None, "ambiguous: several open payouts with the same amount"
    return None, "amount does not match any open payout for this address"


async def process_outgoing(session: AsyncSession, transfer: IncomingTransfer) -> bool:
    """Settle one observed outgoing transfer. Returns True if a payout was confirmed."""
    if await _already_recorded(session, transfer):
        return False

    payout, reason = await _match_payout(session, transfer)
    if payout is None:
        await _record(session, transfer, "unmatched", meta={"reason": reason})
        log.warning(
            "payout.unmatched_transfer",
            txid=transfer.txid, to=transfer.to_address,
            amount=str(transfer.amount), network=transfer.network, reason=reason,
        )
        return False

    await _record(
        session, transfer, "paid",
        payout_id=payout.id, user_id=payout.referrer_user_id, meta={"match": reason},
    )
    # operator_id stays whoever approved it; auto-confirmation doesn't invent an actor
    await referral.mark_payout_paid(
        session, payout.id, tx_hash=transfer.txid, operator_id=payout.operator_id
    )
    log.info(
        "payout.confirmed_onchain",
        payout=payout.id, txid=transfer.txid, amount=str(transfer.amount),
        network=transfer.network,
    )
    return True


async def run_payout_tick(
    session: AsyncSession, client: OutgoingCapableClient, config: OnchainConfig
) -> int:
    """One pass per chain: scan our payout wallets for sends, confirm matching payouts."""
    sources: list[PayoutSource] = config.payout_sources_for_chain(client.chain)
    if not sources:
        return 0

    head = await client.get_block_height()
    backfill = _TRON_BACKFILL_MS if client.chain == "tron" else _EVM_BACKFILL_BLOCKS
    cursor = await _cursor(session, client.chain, head, backfill)
    from_block = cursor.last_scanned_block + 1
    if head < from_block:
        return 0

    confirmed = 0
    for source in sources:
        rail = PAYOUT_RAILS[source.network]
        # Must go through the config, not the bare asset registry: on testnet the USDT
        # contract is overridden, and scanning for the mainnet one matches nothing.
        spec = config.payout_spec(source)
        if spec is None or not spec.token_contract:
            continue
        transfers = await client.scan_outgoing(
            from_block=from_block,
            to_block=head,
            source_address=source.address,
            token_contract=spec.token_contract,
            decimals=spec.decimals,
            asset=rail.asset,
            network=source.network,
        )
        for transfer in transfers:
            try:
                async with session.begin_nested():
                    if await process_outgoing(session, transfer):
                        confirmed += 1
            except Exception:
                log.exception("payout.transfer_failed", txid=transfer.txid)

    cursor.last_scanned_block = head
    cursor.updated_at = _utcnow()
    return confirmed

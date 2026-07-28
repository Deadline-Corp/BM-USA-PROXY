"""Append-only writers for the on-chain deposit ledger and invoice status history.

Every call INSERTs a new row — statuses are never updated in place, so the full
history of "when did we see it, how much, which address, which user, what state" is
always reconstructable (doc 15 §7).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onchain import InvoiceStatusHistory, OnchainDepositLedger
from app.services.payments.onchain.chain_client import IncomingTransfer


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LedgerWriter:
    """Thin append-only writer bound to a session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_deposit(
        self,
        transfer: IncomingTransfer,
        status: str,
        *,
        invoice_id: int | None = None,
        user_id: int | None = None,
        confirmations: int | None = None,
        amount_usd: Decimal | None = None,
        meta: dict | None = None,
    ) -> OnchainDepositLedger:
        """Append one ledger row capturing ``transfer`` in state ``status``."""
        row = OnchainDepositLedger(
            status=status,
            chain=transfer.chain,
            asset=transfer.asset,
            network=transfer.network,
            txid=transfer.txid,
            log_index=transfer.log_index,
            from_address=transfer.from_address,
            to_address=transfer.to_address,
            amount=transfer.amount,
            amount_usd=amount_usd,
            confirmations=confirmations if confirmations is not None else transfer.confirmations,
            block_number=transfer.block_number,
            block_time=transfer.block_time,
            observed_at=_utcnow(),
            invoice_id=invoice_id,
            user_id=user_id,
            meta=meta or {},
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def record_invoice_status(
        self,
        invoice_id: int,
        *,
        from_status: str | None,
        to_status: str,
        reason: str | None = None,
        actor: str = "system",
        deposit_ledger_id: int | None = None,
    ) -> InvoiceStatusHistory:
        """Append one invoice status-transition row."""
        row = InvoiceStatusHistory(
            invoice_id=invoice_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            actor=actor,
            deposit_ledger_id=deposit_ledger_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def latest_status(
        self, txid: str, log_index: int, *, asset: str, network: str
    ) -> str | None:
        """Current state of a transfer = the most recent ledger row for its identity.

        Scoped by asset+network too, so two transfers sharing a (txid, log_index=0) but a
        different asset (e.g. SOL + USDC in one Solana tx) don't shadow each other.
        """
        stmt = (
            select(OnchainDepositLedger.status)
            .where(
                OnchainDepositLedger.txid == txid,
                OnchainDepositLedger.log_index == log_index,
                OnchainDepositLedger.asset == asset,
                OnchainDepositLedger.network == network,
            )
            .order_by(OnchainDepositLedger.created_at.desc(), OnchainDepositLedger.id.desc())
            .limit(1)
        )
        value: str | None = await self.session.scalar(stmt)
        return value

    async def latest_deposit(
        self, txid: str, log_index: int | None = None
    ) -> OnchainDepositLedger | None:
        """Most recent ledger row for a transfer — used to re-finalize stragglers.

        Scoped by log_index when known, so a multi-output tx re-loads the exact output
        that paid this invoice rather than an arbitrary row sharing the txid.
        """
        stmt = select(OnchainDepositLedger).where(OnchainDepositLedger.txid == txid)
        if log_index is not None:
            stmt = stmt.where(OnchainDepositLedger.log_index == log_index)
        stmt = stmt.order_by(
            OnchainDepositLedger.created_at.desc(), OnchainDepositLedger.id.desc()
        ).limit(1)
        row: OnchainDepositLedger | None = await self.session.scalar(stmt)
        return row

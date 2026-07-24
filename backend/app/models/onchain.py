"""On-chain payment watcher tables (doc 15).

Historicity is APPEND-ONLY: a status change is a new row (INSERT), never an UPDATE, so the
full lifecycle of every observed transfer and every invoice is always reconstructable.
``invoices.status`` remains only a denormalised current-state projection; the source of
truth is ``onchain_deposit_ledger`` + ``invoice_status_history``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.models.base import Base, created_at_col, pk

# Lifecycle of an on-chain transfer as it moves through the watcher.
LEDGER_STATUSES = (
    "detected",        # first seen on-chain (may be 0-conf)
    "confirming",      # seen, below the confirmation threshold
    "confirmed",       # reached the confirmation threshold
    "matched",         # tied to an invoice
    "paid",            # matched + amount OK → provisioning triggered
    "underpaid",       # amount short beyond tolerance → manual review
    "overpaid",        # amount above expected → accepted, excess logged
    "unmatched",       # could not be tied to any open invoice
    "expired_deposit",  # arrived after the invoice TTL
    "orphaned",        # dust / wrong asset / unknown
    "reorg_rollback",  # a previously-final tx was rolled back by a reorg
)


class OnchainDepositLedger(Base):
    """APPEND-ONLY. One row per status transition of an observed on-chain transfer.

    Current state of a transfer = the latest row (by ``created_at``) for its
    ``(txid, log_index)``; see the ``v_deposit_current`` view.
    """

    __tablename__ = "onchain_deposit_ledger"

    id: Mapped[int] = pk()
    created_at: Mapped[datetime] = created_at_col()
    status: Mapped[str] = mapped_column(Text, nullable=False)
    chain: Mapped[str] = mapped_column(Text, nullable=False)
    asset: Mapped[str] = mapped_column(Text, nullable=False)
    network: Mapped[str] = mapped_column(Text, nullable=False)
    txid: Mapped[str] = mapped_column(Text, nullable=False)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    from_address: Mapped[str | None] = mapped_column(Text)
    to_address: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(38, 18), nullable=False)
    amount_usd: Mapped[float | None] = mapped_column(Numeric(38, 18))
    confirmations: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    block_number: Mapped[int | None] = mapped_column(BigInteger)
    block_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        CheckConstraint(
            "status IN ('" + "','".join(LEDGER_STATUSES) + "')", name="status_valid"
        ),
        Index("ix_ledger_tx", "txid", "log_index"),
        Index("ix_ledger_invoice", "invoice_id"),
        Index("ix_ledger_status", "status"),
        Index("ix_ledger_to_address", "to_address"),
        Index("ix_ledger_user", "user_id"),
        Index("ix_ledger_created", text("created_at DESC")),
    )


class InvoiceStatusHistory(Base):
    """APPEND-ONLY. One row per invoice status transition."""

    __tablename__ = "invoice_status_history"

    id: Mapped[int] = pk()
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text, nullable=False, server_default="system")
    deposit_ledger_id: Mapped[int | None] = mapped_column(
        ForeignKey("onchain_deposit_ledger.id")
    )
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        Index("ix_invoice_status_history_invoice", "invoice_id", text("created_at DESC")),
    )


class ChainCursor(Base):
    """Per-chain block-scan progress (last fully-scanned block)."""

    __tablename__ = "chain_cursors"

    chain: Mapped[str] = mapped_column(Text, primary_key=True)
    last_scanned_block: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

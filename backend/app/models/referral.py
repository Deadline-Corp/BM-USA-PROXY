"""Referral ledger (append-only) and payouts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.models.base import Base, created_at_col, pk, updated_at_col


class ReferralLedger(Base):
    __tablename__ = "referral_ledger"

    id: Mapped[int] = pk()
    referrer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    referee_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="accrual")
    base_amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="hold")
    hold_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payout_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("payouts.id", use_alter=True, name="fk_referral_ledger_payout_id_payouts"),
    )
    reversal_of_id: Mapped[int | None] = mapped_column(ForeignKey("referral_ledger.id"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    __table_args__ = (
        CheckConstraint("kind IN ('accrual','reversal')", name="kind_valid"),
        CheckConstraint(
            "status IN ('hold','available','requested','paid','reversed')", name="status_valid"
        ),
        Index(
            "uq_ledger_accrual_per_order",
            "order_id",
            unique=True,
            postgresql_where="kind = 'accrual'",
        ),
        Index("ix_ledger_referrer", "referrer_user_id", "status"),
        Index("ix_ledger_release", "status", "hold_until", postgresql_where="status = 'hold'"),
    )


class Payout(Base):
    __tablename__ = "payouts"

    id: Mapped[int] = pk()
    referrer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    wallet_address: Mapped[str] = mapped_column(Text, nullable=False)
    network: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="requested")
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    tx_hash: Mapped[str | None] = mapped_column(Text)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('requested','approved','paid','rejected')", name="status_valid"
        ),
        Index("ix_payouts_queue", "status", "requested_at"),
    )

"""Commerce: orders, invoices, payment_events, refunds."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.models.base import Base, created_at_col, pk, updated_at_col


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = pk()
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariffs.id"), nullable=False)
    tariff_code: Mapped[str] = mapped_column(Text, nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    carrier: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="awaiting_payment")
    is_extension: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    extends_access_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("accesses.id", use_alter=True, name="fk_orders_extends_access_id_accesses"),
    )
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default="twa")
    referrer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    source_post_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("posts.id", use_alter=True, name="fk_orders_source_post_id_posts")
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting_payment','paid','provisioning','completed',"
            "'cancelled','expired','refunded','manual_review')",
            name="status_valid",
        ),
        CheckConstraint("origin IN ('twa','admin')", name="origin_valid"),
        CheckConstraint(
            "carrier IN ('T-Mobile','Verizon','AT&T') OR carrier IS NULL", name="carrier_valid"
        ),
        Index("ix_orders_user", "user_id", text("created_at DESC")),
        Index(
            "ix_orders_status",
            "status",
            postgresql_where=text("status IN ('awaiting_payment','provisioning','manual_review')"),
        ),
    )


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = pk()
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_invoice_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="created")
    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    crypto_currency: Mapped[str | None] = mapped_column(Text)
    crypto_network: Mapped[str | None] = mapped_column(Text)
    crypto_amount: Mapped[float | None] = mapped_column(Numeric(30, 12))
    pay_address: Mapped[str | None] = mapped_column(Text)
    payment_url: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    __table_args__ = (
        UniqueConstraint("provider", "provider_invoice_id", name="provider_invoice"),
        CheckConstraint(
            "status IN ('created','pending','confirming','paid','underpaid','overpaid',"
            "'expired','failed','manual_review')",
            name="status_valid",
        ),
        Index("ix_invoices_order", "order_id"),
        Index(
            "ix_invoices_pending",
            "status",
            "expires_at",
            postgresql_where=text("status IN ('created','pending','confirming')"),
        ),
    )


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id: Mapped[int] = pk()
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(Text)
    provider_invoice_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_result: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index(
            "uq_payment_events_dedupe",
            "provider",
            "provider_event_id",
            unique=True,
            postgresql_where=text("provider_event_id IS NOT NULL"),
        ),
    )


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = pk()
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    wallet_address: Mapped[str | None] = mapped_column(Text)
    tx_hash: Mapped[str | None] = mapped_column(Text)
    operator_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()

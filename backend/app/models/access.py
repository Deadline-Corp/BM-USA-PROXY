"""Accesses (issued proxies) and their append-only lifecycle events."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.models.base import Base, created_at_col, pk, updated_at_col


class Access(Base):
    __tablename__ = "accesses"

    id: Mapped[int] = pk()
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    connection_id: Mapped[int] = mapped_column(ForeignKey("connections.id"), nullable=False)
    tariff_code: Mapped[str] = mapped_column(Text, nullable=False)
    iproxy_access_id: Mapped[str | None] = mapped_column(Text)
    credentials_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # Fernet(JSON)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="provisioning")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    warned_24h_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warned_1h_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_rotation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotations_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    swap_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    __table_args__ = (
        CheckConstraint(
            "status IN ('provisioning','active','expiring','expired','revoked','failed')",
            name="status_valid",
        ),
        # INVARIANT #2: one live access per connection (dedicated).
        Index(
            "uq_connection_active_access",
            "connection_id",
            unique=True,
            postgresql_where=text("status IN ('provisioning','active','expiring')"),
        ),
        Index("ix_accesses_user", "user_id", text("created_at DESC")),
        Index(
            "ix_accesses_sweep",
            "status",
            "expires_at",
            postgresql_where=text("status IN ('active','expiring')"),
        ),
    )


class AccessEvent(Base):
    __tablename__ = "access_events"

    id: Mapped[int] = pk()
    access_id: Mapped[int] = mapped_column(ForeignKey("accesses.id"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)  # 'system' | 'user' | 'admin:<id>'
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        CheckConstraint(
            "type IN ('issued','rotate_ip','extended','expiry_warning','expired','revoked',"
            "'reissued','config_delivered','provision_failed')",
            name="type_valid",
        ),
        Index("ix_access_events_access", "access_id", text("created_at DESC")),
    )

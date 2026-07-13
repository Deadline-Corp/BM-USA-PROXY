"""Catalog: tariffs, locations, connections (the sellable pool mirror of iproxy)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.models.base import Base, created_at_col, pk, updated_at_col


class Tariff(Base):
    __tablename__ = "tariffs"

    id: Mapped[int] = pk()
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="auto")
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    price_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, server_default="0")
    max_per_user: Mapped[int | None] = mapped_column(Integer)
    max_user_swaps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    auto_issue: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    __table_args__ = (
        CheckConstraint("kind IN ('auto','manual')", name="kind_valid"),
    )


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = pk()
    city: Mapped[str] = mapped_column(Text, nullable=False)
    state_code: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")

    __table_args__ = (UniqueConstraint("city", "state_code", name="city_state"),)


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[int] = pk()
    iproxy_connection_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    carrier: Mapped[str | None] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(Text, nullable=False, server_default="standard")
    is_sellable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    online_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    last_online_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    health_note: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    __table_args__ = (
        CheckConstraint(
            "carrier IN ('T-Mobile','Verizon','AT&T') OR carrier IS NULL", name="carrier_valid"
        ),
        CheckConstraint("tier IN ('stable','standard','reserved')", name="tier_valid"),
        CheckConstraint(
            "online_status IN ('online','offline','unknown')", name="online_status_valid"
        ),
        Index("ix_connections_pool", "is_sellable", "online_status", "location_id"),
    )

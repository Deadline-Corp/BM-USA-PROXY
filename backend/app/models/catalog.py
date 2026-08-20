"""Catalog: tariffs, locations, connections (the sellable pool mirror of iproxy)."""

from __future__ import annotations

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
    text,
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


class StateCity(Base):
    """Which city a state is sold as: "a phone whose name says NV is Las Vegas".

    The client organises their farm by state and writes it into each connection's name
    (`att113_NV`). iproxy exposes no group or state field of its own, and the exit IP's real
    city is not what they want to advertise — Las Vegas is a market, Rolling Meadows is not.
    So this table is the client's own decision, one row per state, editable in the console:
    a farm of 2000 phones needs nine rows here rather than 2000 descriptions.

    Deliberately not merged into `locations`: that table is every city the pool has ever
    reported, discovered from exit IPs, while this one is a short, hand-kept mapping. One
    city can appear in both without meaning the same thing.
    """

    __tablename__ = "state_cities"

    # Two letters, uppercase, one row per state — the state IS the key, so the same state
    # cannot be mapped to two cities by accident.
    state_code: Mapped[str] = mapped_column(Text, primary_key=True)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    updated_at: Mapped[datetime] = updated_at_col()


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
    # Proxy-accesses that exist on this phone in iproxy but were not issued by us —
    # someone created them straight in the iproxy console. Such a phone is occupied even
    # though our own tables show it free, which is exactly the mismatch the client hit on
    # the demo: three phones busy in iproxy, one busy here, and syncing did not help
    # because sync never looked at per-connection accesses.
    external_access_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    external_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Held for an order whose invoice is still unpaid, so the phone quoted at checkout is
    # the phone handed over when the deposit lands. `reserved_until` is the safety valve:
    # every release path can be missed, and a hold with no clock removes a phone from the
    # pool forever. See services.provisioning.allocator.
    reserved_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="SET NULL")
    )
    reserved_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
        CheckConstraint(
            "reserved_order_id IS NULL OR reserved_until IS NOT NULL", name="reservation_dated"
        ),
        Index("ix_connections_pool", "is_sellable", "online_status", "location_id"),
        Index(
            "ix_connections_reserved",
            "reserved_order_id",
            "reserved_until",
            postgresql_where=text("reserved_order_id IS NOT NULL"),
        ),
    )

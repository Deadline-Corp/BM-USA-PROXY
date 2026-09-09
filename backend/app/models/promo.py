"""Promo codes: a percentage off, a window it is good for, and a limit on how often.

The count of uses is not a column. It is the number of `PromoRedemption` rows, because a
cancelled order gives its attempt back and a counter would have to be decremented by
whoever remembered to — the first path that forgot would let a one-use code be spent twice
or never again. Rows are exact, and there is an index for the count.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, pk


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = pk()
    # Upper-cased on the way in and on lookup — a buyer typing "summer" gets the code an
    # operator created as "SUMMER".
    code: Mapped[str] = mapped_column(Text, nullable=False)
    percent_off: Mapped[int] = mapped_column(Integer, nullable=False)
    # Both optional. Neither set means "good from now until somebody deletes it", which is
    # what an operator means by a code with no expiry.
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # None = unlimited. 1 = one person. 50 = a campaign.
    max_uses: Mapped[int | None] = mapped_column(Integer)
    # 'purchase' = new purchases only; 'any' = extensions too. Per code, because the client
    # wanted to decide it campaign by campaign rather than once for the whole system.
    applies_to: Mapped[str] = mapped_column(Text, nullable=False, server_default="any")
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    created_at: Mapped[datetime] = created_at_col()
    # Soft delete: orders sold under this code still point at it, and removing a spent
    # campaign is not a request to rewrite what it sold.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("percent_off > 0 AND percent_off <= 100", name="percent_sane"),
        CheckConstraint("applies_to IN ('purchase','any')", name="applies_to_valid"),
        CheckConstraint("max_uses IS NULL OR max_uses > 0", name="max_uses_sane"),
        CheckConstraint(
            "starts_at IS NULL OR expires_at IS NULL OR expires_at > starts_at",
            name="window_ordered",
        ),
        # Among the living only, so a name can be used again after its campaign is gone.
        Index(
            "uq_promo_codes_code_live",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class PromoRedemption(Base):
    """One consumed use. Deleted when its order is cancelled or expires."""

    __tablename__ = "promo_redemptions"

    id: Mapped[int] = pk()
    promo_code_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    percent_off: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        # "One per buyer" as a thing the database refuses, not a check the application has
        # to remember at every call site.
        Index("uq_promo_redemption_user", "promo_code_id", "user_id", unique=True),
        # And one per order, so a retried checkout cannot count twice against the limit.
        Index("uq_promo_redemption_order", "order_id", unique=True),
        Index("ix_promo_redemptions_code", "promo_code_id"),
    )

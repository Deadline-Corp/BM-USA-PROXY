"""promo codes with a percentage discount, a validity window and a use limit

Two tables, deliberately.

`promo_codes` is what an operator writes. `promo_redemptions` is what has actually been
consumed, and it is the only place the count lives — a `used_count` column on the code
would be a second copy of the same fact, and the two drift the first time an order is
cancelled. Counting rows is exact and the table is small.

The redemption row is also what enforces "one per buyer": a unique index on
(promo_code_id, user_id) turns the rule into something the database refuses rather than
something the application remembers to check. It is deleted when an order is cancelled or
expires, which is what gives the buyer their attempt back — a one-use code must not burn on
an invoice nobody paid.

The order keeps `promo_code_id` and `discount_usd` of its own. That is the record of what
was charged and it has to survive the redemption being released, and the code being
deleted. `ON DELETE SET NULL` rather than a cascade for the same reason: removing a
finished campaign must never remove the orders sold under it.

Revision ID: 0032_promo_codes
Revises: 0031_access_event_reboot
Create Date: 2026-09-08
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_promo_codes"
down_revision: str | None = "0031_access_event_reboot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # Stored upper-case; the service upper-cases on the way in and on lookup, so
        # "summer" and "SUMMER" are one code and a buyer's capitalisation never matters.
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("percent_off", sa.Integer(), nullable=False),
        # Both ends optional: a code with neither works from creation until it is deleted,
        # which is what an operator means by "no expiry".
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        # NULL = unlimited. 1 = personal, 50 = a campaign.
        sa.Column("max_uses", sa.Integer()),
        # 'purchase' — new purchases only. 'any' — extensions as well. The client asked for
        # this per code rather than as one global rule.
        sa.Column("applies_to", sa.Text(), nullable=False, server_default="any"),
        sa.Column("note", sa.Text()),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("admin_users.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # Soft delete. A code that has sold something cannot be removed outright without
        # taking the history of those sales with it, and an operator deleting a spent
        # campaign is not asking to rewrite what it sold.
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("percent_off > 0 AND percent_off <= 100", name="percent_sane"),
        sa.CheckConstraint("applies_to IN ('purchase','any')", name="applies_to_valid"),
        sa.CheckConstraint("max_uses IS NULL OR max_uses > 0", name="max_uses_sane"),
        sa.CheckConstraint(
            "starts_at IS NULL OR expires_at IS NULL OR expires_at > starts_at",
            name="window_ordered",
        ),
    )
    # Unique among the living only, so a name can be reused after its campaign is deleted.
    op.create_index(
        "uq_promo_codes_code_live",
        "promo_codes",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "promo_redemptions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "promo_code_id",
            sa.BigInteger(),
            sa.ForeignKey("promo_codes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "order_id",
            sa.BigInteger(),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("percent_off", sa.Integer(), nullable=False),
        sa.Column("discount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # One per buyer, enforced here rather than in a check the application has to remember.
    op.create_index(
        "uq_promo_redemption_user", "promo_redemptions", ["promo_code_id", "user_id"], unique=True
    )
    # One per order, so a retry cannot count twice against the limit.
    op.create_index("uq_promo_redemption_order", "promo_redemptions", ["order_id"], unique=True)
    op.create_index("ix_promo_redemptions_code", "promo_redemptions", ["promo_code_id"])

    op.add_column(
        "orders",
        sa.Column("promo_code_id", sa.BigInteger(), sa.ForeignKey("promo_codes.id", ondelete="SET NULL")),
    )
    op.add_column(
        "orders",
        sa.Column(
            "discount_usd", sa.Numeric(10, 2), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "discount_usd")
    op.drop_column("orders", "promo_code_id")
    op.drop_index("ix_promo_redemptions_code", table_name="promo_redemptions")
    op.drop_index("uq_promo_redemption_order", table_name="promo_redemptions")
    op.drop_index("uq_promo_redemption_user", table_name="promo_redemptions")
    op.drop_table("promo_redemptions")
    op.drop_index("uq_promo_codes_code_live", table_name="promo_codes")
    op.drop_table("promo_codes")

"""orders.quantity — one order can now buy several proxies

Buyers were asking for ten and being sold one at a time, which meant ten invoices, ten
transfers and ten sets of network fees for a single purchase.

Existing rows are quantity 1, which is exactly what they were, so no backfill is needed
beyond the default.

Revision ID: 0027_order_quantity
Revises: 0026_conversation_via_ai
Create Date: 2026-08-20
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_order_quantity"
down_revision: str | None = "0026_conversation_via_ai"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint("quantity_positive", "orders", "quantity >= 1")


def downgrade() -> None:
    op.drop_constraint("quantity_positive", "orders", type_="check")
    op.drop_column("orders", "quantity")

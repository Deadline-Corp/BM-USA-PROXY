"""connections.reserved_order_id / reserved_until — hold stock for an unpaid invoice

A buyer who asked for ten proxies was quoted ten, then paid, and by the time the deposit
confirmed somebody else had bought three of them. The order landed in manual review and a
human had to settle a shortfall that nobody caused.

The phones are now taken off the shelf the moment the invoice is raised and put back when
it expires. ``reserved_until`` is what makes that safe to run unattended: every release
path can fail, be skipped, or be lost to a crash, and a hold with no clock on it removes a
phone from the pool permanently. With one, the worst outcome is a phone that sits idle
until the invoice would have expired anyway.

Revision ID: 0028_connection_reservation
Revises: 0027_order_quantity
Create Date: 2026-08-20
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_connection_reservation"
down_revision: str | None = "0027_order_quantity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("reserved_order_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "connections",
        sa.Column("reserved_until", sa.DateTime(timezone=True), nullable=True),
    )
    # SET NULL rather than CASCADE: deleting an order must free the phone, never delete it.
    op.create_foreign_key(
        "fk_connections_reserved_order_id_orders",
        "connections",
        "orders",
        ["reserved_order_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # A hold must carry a deadline — one that never expires is a phone that leaves the pool
    # for good. Stated one-directionally on purpose: the FK above nulls the owner when an
    # order is deleted and cannot touch the timestamp in the same statement, so requiring
    # both-or-neither would make deleting an order fail outright. An expiry with no owner
    # is harmless instead: every query treats an ownerless hold as free, and the sweeper
    # clears the leftover.
    op.create_check_constraint(
        "reservation_dated",
        "connections",
        "reserved_order_id IS NULL OR reserved_until IS NOT NULL",
    )
    # Partial: reservations are a small minority of rows, and every query that touches them
    # is either "what does this order hold" or "what has lapsed".
    op.create_index(
        "ix_connections_reserved",
        "connections",
        ["reserved_order_id", "reserved_until"],
        postgresql_where=sa.text("reserved_order_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_connections_reserved", table_name="connections")
    op.drop_constraint("reservation_dated", "connections", type_="check")
    op.drop_constraint("fk_connections_reserved_order_id_orders", "connections", type_="foreignkey")
    op.drop_column("connections", "reserved_until")
    op.drop_column("connections", "reserved_order_id")

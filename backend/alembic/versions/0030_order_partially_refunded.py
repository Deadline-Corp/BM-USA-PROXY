"""orders.status gains 'partially_refunded'

The refund endpoint learned to tell a partial refund from a full one, so that the ledger
stops claiming an order was refunded in full when only part of it was. It wrote the new
status without widening the check constraint, and nothing caught it because the branch
shipped untested: measured against the real schema, `update orders set
status='partially_refunded'` fails with

    new row for relation "orders" violates check constraint "ck_orders_status_valid"

so every partial refund would have rolled back at the last moment — the operator clicking
Refund, seeing an error, and the money not moving.

Revision ID: 0030_order_partially_refunded
Revises: 0029_faq_use_in_bot
Create Date: 2026-08-22
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0030_order_partially_refunded"
down_revision: str | None = "0029_faq_use_in_bot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = (
    "awaiting_payment",
    "paid",
    "provisioning",
    "completed",
    "cancelled",
    "expired",
    "refunded",
    "manual_review",
)
_NEW = (*_STATUSES, "partially_refunded")


def _rewrite(values: tuple[str, ...]) -> None:
    # Bare name: the alembic naming convention prepends ck_orders_ itself, and
    # passing the full name once produced ck_orders_ck_orders_status_valid.
    op.drop_constraint("status_valid", "orders", type_="check")
    joined = ",".join(f"'{v}'" for v in values)
    op.create_check_constraint("status_valid", "orders", f"status IN ({joined})")


def upgrade() -> None:
    _rewrite(_NEW)


def downgrade() -> None:
    # Anything already partially refunded has to land somewhere the old constraint allows.
    # 'refunded' is the honest choice of the two available: money did go back, and calling
    # it 'paid' would hide a refund that happened.
    op.execute("UPDATE orders SET status = 'refunded' WHERE status = 'partially_refunded'")
    _rewrite(_STATUSES)

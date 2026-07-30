"""payout watcher: ledger direction + payout link

Variant 1 of the referral payout design (client decision 2026-07-30): a human sends the
USDT, and the watcher confirms it on-chain. The same append-only ledger now records
OUTGOING transfers too, so a payout's proof lives next to the deposits.

- onchain_deposit_ledger.direction: 'in' (deposits, the default) | 'out' (payouts)
- onchain_deposit_ledger.payout_id: which payout an outgoing transfer settled

Revision ID: 0007_payout_watcher
Revises: 0006_onchain_amount_uniqueness
Create Date: 2026-07-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_payout_watcher"
down_revision: str | None = "0006_onchain_amount_uniqueness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "onchain_deposit_ledger",
        sa.Column("direction", sa.Text(), server_default="in", nullable=False),
    )
    op.add_column(
        "onchain_deposit_ledger", sa.Column("payout_id", sa.BigInteger(), nullable=True)
    )
    op.create_check_constraint(
        "ck_onchain_deposit_ledger_direction_valid",
        "onchain_deposit_ledger",
        "direction IN ('in','out')",
    )
    op.create_foreign_key(
        "fk_onchain_deposit_ledger_payout_id_payouts",
        "onchain_deposit_ledger",
        "payouts",
        ["payout_id"],
        ["id"],
    )
    op.create_index("ix_ledger_payout", "onchain_deposit_ledger", ["payout_id"])
    op.create_index("ix_ledger_direction", "onchain_deposit_ledger", ["direction"])


def downgrade() -> None:
    op.drop_index("ix_ledger_direction", table_name="onchain_deposit_ledger")
    op.drop_index("ix_ledger_payout", table_name="onchain_deposit_ledger")
    op.drop_constraint(
        "fk_onchain_deposit_ledger_payout_id_payouts",
        "onchain_deposit_ledger",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_onchain_deposit_ledger_direction_valid",
        "onchain_deposit_ledger",
        type_="check",
    )
    op.drop_column("onchain_deposit_ledger", "payout_id")
    op.drop_column("onchain_deposit_ledger", "direction")

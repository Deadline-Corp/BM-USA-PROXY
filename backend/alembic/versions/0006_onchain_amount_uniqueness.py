"""on-chain: collision-free invoice amounts (F1) + matched_log_index (F7) + block_hash (F8)

- invoices.matched_log_index: which output/log of matched_txid paid this invoice, so the
  finalize pass reloads the exact transfer (not just "some row for this txid").
- uq_onchain_open_invoice_amount: a partial-unique index enforcing that no two OPEN
  on-chain invoices on the same receiving rail share an expected amount — the DB backstop
  behind the amount-uniquification nudge in orders.create_order.
- onchain_deposit_ledger.block_hash: recorded so a reorg re-validation can tell whether a
  finalized deposit's block is still canonical.

Revision ID: 0006_onchain_amount_uniqueness
Revises: 0005_onchain_ledger
Create Date: 2026-07-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_onchain_amount_uniqueness"
down_revision: str | None = "0005_onchain_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("matched_log_index", sa.Integer(), nullable=True))
    op.add_column(
        "onchain_deposit_ledger", sa.Column("block_hash", sa.Text(), nullable=True)
    )
    op.create_index(
        "uq_onchain_open_invoice_amount",
        "invoices",
        ["crypto_currency", "crypto_network", "pay_address", "crypto_amount"],
        unique=True,
        postgresql_where=sa.text(
            "provider = 'onchain' AND status IN ('pending', 'confirming')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_onchain_open_invoice_amount", table_name="invoices")
    op.drop_column("onchain_deposit_ledger", "block_hash")
    op.drop_column("invoices", "matched_log_index")

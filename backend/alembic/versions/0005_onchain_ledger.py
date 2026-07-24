"""on-chain payment watcher: append-only deposit ledger + invoice status history + cursors

Adds the schema for the self-hosted multi-chain on-chain payment watcher (doc 15):
- invoices: extra columns for the on-chain provider (chain, locked rate, tolerance, reference…)
- onchain_deposit_ledger: APPEND-ONLY log of every observed on-chain transfer + status change
- invoice_status_history: APPEND-ONLY log of invoice status transitions
- chain_cursors: per-chain block-scan cursor

Revision ID: 0005_onchain_ledger
Revises: 0004_conversation_messages
Create Date: 2026-07-24

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_onchain_ledger"
down_revision: str | None = "0004_conversation_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_LEDGER_STATUSES = (
    "detected",
    "confirming",
    "confirmed",
    "matched",
    "paid",
    "underpaid",
    "overpaid",
    "unmatched",
    "expired_deposit",
    "orphaned",
    "reorg_rollback",
)


def upgrade() -> None:
    # ── invoices: on-chain provider columns ───────────────────────────────
    op.add_column("invoices", sa.Column("chain", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("base_amount", sa.Numeric(38, 18), nullable=True))
    op.add_column("invoices", sa.Column("amount_tolerance", sa.Numeric(38, 18), nullable=True))
    op.add_column("invoices", sa.Column("locked_rate", sa.Numeric(30, 12), nullable=True))
    op.add_column("invoices", sa.Column("rate_locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("invoices", sa.Column("reference_pubkey", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("matched_txid", sa.Text(), nullable=True))
    op.add_column(
        "invoices",
        sa.Column("confirmations", sa.Integer(), server_default="0", nullable=False),
    )

    # ── onchain_deposit_ledger: append-only, one row per status transition ─
    op.create_table(
        "onchain_deposit_ledger",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("chain", sa.Text(), nullable=False),
        sa.Column("asset", sa.Text(), nullable=False),
        sa.Column("network", sa.Text(), nullable=False),
        sa.Column("txid", sa.Text(), nullable=False),
        sa.Column("log_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("from_address", sa.Text(), nullable=True),
        sa.Column("to_address", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("amount_usd", sa.Numeric(38, 18), nullable=True),
        sa.Column("confirmations", sa.Integer(), server_default="0", nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("block_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invoice_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "meta", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('" + "','".join(_LEDGER_STATUSES) + "')",
            name=op.f("ck_onchain_deposit_ledger_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["invoices.id"],
            name=op.f("fk_onchain_deposit_ledger_invoice_id_invoices"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_onchain_deposit_ledger_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_onchain_deposit_ledger")),
    )
    op.create_index("ix_ledger_tx", "onchain_deposit_ledger", ["txid", "log_index"])
    op.create_index("ix_ledger_invoice", "onchain_deposit_ledger", ["invoice_id"])
    op.create_index("ix_ledger_status", "onchain_deposit_ledger", ["status"])
    op.create_index("ix_ledger_to_address", "onchain_deposit_ledger", ["to_address"])
    op.create_index("ix_ledger_user", "onchain_deposit_ledger", ["user_id"])
    op.create_index("ix_ledger_created", "onchain_deposit_ledger", [sa.text("created_at DESC")])

    # convenience view: latest ledger row per on-chain transfer = its current state
    op.execute(
        """
        CREATE VIEW v_deposit_current AS
        SELECT DISTINCT ON (txid, log_index) *
        FROM onchain_deposit_ledger
        ORDER BY txid, log_index, created_at DESC
        """
    )

    # ── invoice_status_history: append-only invoice lifecycle ─────────────
    op.create_table(
        "invoice_status_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("invoice_id", sa.BigInteger(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor", sa.Text(), server_default="system", nullable=False),
        sa.Column("deposit_ledger_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["invoices.id"],
            name=op.f("fk_invoice_status_history_invoice_id_invoices"),
        ),
        sa.ForeignKeyConstraint(
            ["deposit_ledger_id"], ["onchain_deposit_ledger.id"],
            name=op.f("fk_invoice_status_history_deposit_ledger_id_onchain_deposit_ledger"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_status_history")),
    )
    op.create_index(
        "ix_invoice_status_history_invoice",
        "invoice_status_history",
        ["invoice_id", sa.text("created_at DESC")],
    )

    # ── chain_cursors: per-chain block-scan progress ──────────────────────
    op.create_table(
        "chain_cursors",
        sa.Column("chain", sa.Text(), nullable=False),
        sa.Column("last_scanned_block", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("chain", name=op.f("pk_chain_cursors")),
    )


def downgrade() -> None:
    op.drop_table("chain_cursors")
    op.drop_index("ix_invoice_status_history_invoice", table_name="invoice_status_history")
    op.drop_table("invoice_status_history")
    op.execute("DROP VIEW IF EXISTS v_deposit_current")
    for ix in (
        "ix_ledger_created",
        "ix_ledger_user",
        "ix_ledger_to_address",
        "ix_ledger_status",
        "ix_ledger_invoice",
        "ix_ledger_tx",
    ):
        op.drop_index(ix, table_name="onchain_deposit_ledger")
    op.drop_table("onchain_deposit_ledger")
    for col in (
        "confirmations",
        "matched_txid",
        "reference_pubkey",
        "rate_locked_at",
        "locked_rate",
        "amount_tolerance",
        "base_amount",
        "chain",
    ):
        op.drop_column("invoices", col)

"""access_vpn_configs: OpenVPN / WireGuard issued per access

The mini-app has offered "OpenVPN config" and "WireGuard config" buttons since launch.
They queued a notification saying "your config is on the way" and nothing ever sent one —
there was no code that fetched a config at all. Both are real iproxy resources
(`ovpn-access` / `wg-access` on a connection, verified live 2026-08-12), so this table is
what makes the buttons true.

Two rules live in the schema rather than in code:

- **One config per protocol per access** (unique index). Two taps on the button must not
  create two configs, and iproxy caps them at 20 per connection — without the constraint
  one customer could exhaust a phone and block every other buyer on it.
- **Configs die with the access** (FK ON DELETE CASCADE, plus explicit revocation in
  lifecycle.revoke_access). Storing iproxy's id is the whole point: without it there is
  nothing to delete, and a WireGuard tunnel sold for a month keeps working forever.

Revision ID: 0008_access_vpn_configs
Revises: 0007_payout_watcher
Create Date: 2026-08-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_access_vpn_configs"
down_revision: str | None = "0007_payout_watcher"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "access_vpn_configs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("access_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("iproxy_vpn_access_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["access_id"], ["accesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("kind IN ('ovpn','wg')", name="kind_valid"),
    )
    op.create_index(
        "uq_access_vpn_kind", "access_vpn_configs", ["access_id", "kind"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_access_vpn_kind", table_name="access_vpn_configs")
    op.drop_table("access_vpn_configs")

"""connections: count proxy-accesses that iproxy has but we did not issue

A phone can be occupied without any row of ours saying so: an operator creates a
proxy-access straight in the iproxy console and that phone is serving traffic. Our pool
counted it free and the allocator would happily sell it a second time.

Seen on the client's demo — three phones busy in the iproxy console, one busy in the
admin panel, and pressing Sync changed nothing, because the sync only ever read the
connection list, never each connection's accesses.

Revision ID: 0018_connection_external_holds
Revises: 0017_access_auto_rotate
Create Date: 2026-08-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_connection_external_holds"
down_revision: str | None = "0017_access_auto_rotate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "connections",
        sa.Column(
            "external_access_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "connections",
        sa.Column("external_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("connections", "external_checked_at")
    op.drop_column("connections", "external_access_count")

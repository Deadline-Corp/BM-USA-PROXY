"""accesses: track the socks5 access and the changeip action link

An issued access has always been three resources on iproxy, but only one id was stored:
the http proxy-access. The socks5 access and the buyer's changeip action link were
either not created at all or created and forgotten — and anything we cannot name, we
cannot delete. A forgotten socks5 access keeps serving traffic after the paid period
ends; a forgotten action link keeps rotating a phone that now belongs to somebody else.

Both columns are nullable: accesses issued before this migration have no such resources,
and revoke skips whatever is null.

Revision ID: 0016_access_socks5_and_link
Revises: 0015_media_assets
Create Date: 2026-08-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_access_socks5_and_link"
down_revision: str | None = "0015_media_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("accesses", sa.Column("iproxy_socks5_access_id", sa.Text(), nullable=True))
    op.add_column("accesses", sa.Column("iproxy_action_link_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("accesses", "iproxy_action_link_id")
    op.drop_column("accesses", "iproxy_socks5_access_id")

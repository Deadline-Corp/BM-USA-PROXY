"""connections.geo_* — what our own GeoIP lookup says about a phone's real exit IP

`location_id` is what a connection is *sold as* — an operator's edit, once set, and
sync_pool has never touched it after first sight. Until now even that *first* sight
leaned on iproxy's own app_data.ip_city to pick a city, and that field is not
trustworthy: measured live against the client's account, iproxy named a Milwaukee-area
Verizon phone "Boston". These columns are the separate, honest half — what a local
GeoIP database says about the phone's actual exit IP, refreshed automatically by
sync_pool, never edited by an operator. geo_resolved_at is what lets a phone that has
never been looked up (all of the pool, the first pass after this ships) be told apart
from one that was looked up a moment ago.

Revision ID: 0013_connection_geo
Revises: 0012_admin_delete
Create Date: 2026-08-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_connection_geo"
down_revision: str | None = "0012_admin_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("geo_city", sa.Text(), nullable=True))
    op.add_column("connections", sa.Column("geo_state", sa.Text(), nullable=True))
    op.add_column("connections", sa.Column("geo_ip", sa.Text(), nullable=True))
    op.add_column(
        "connections", sa.Column("geo_resolved_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("connections", "geo_resolved_at")
    op.drop_column("connections", "geo_ip")
    op.drop_column("connections", "geo_state")
    op.drop_column("connections", "geo_city")

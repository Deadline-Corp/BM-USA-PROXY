"""connections.geo_* — dropped, iproxy's own reported city is trusted again

0013 added geo_city/geo_state/geo_ip/geo_resolved_at on the theory that iproxy's own
app_data.ip_city was unreliable. Checked against the live account after shipping that
change, it was not: iproxy's claimed city for three test phones matched our own database
exactly (Saint Francis WI, Sun Prairie WI, Boston MA). The real bug was elsewhere —
sync_pool only ever set location_id on a connection's first sighting, so a phone's sold
city never followed its exit IP after that, GeoIP or not. That is fixed in sync_pool
itself (location_id is now re-resolved from app_data.ip_city on every pass); these columns
were the wrong fix for the right symptom and have no reader left.

Revision ID: 0014_drop_connection_geo
Revises: 0013_connection_geo
Create Date: 2026-08-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_drop_connection_geo"
down_revision: str | None = "0013_connection_geo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("connections", "geo_resolved_at")
    op.drop_column("connections", "geo_ip")
    op.drop_column("connections", "geo_state")
    op.drop_column("connections", "geo_city")


def downgrade() -> None:
    op.add_column("connections", sa.Column("geo_city", sa.Text(), nullable=True))
    op.add_column("connections", sa.Column("geo_state", sa.Text(), nullable=True))
    op.add_column("connections", sa.Column("geo_ip", sa.Text(), nullable=True))
    op.add_column(
        "connections", sa.Column("geo_resolved_at", sa.DateTime(timezone=True), nullable=True)
    )

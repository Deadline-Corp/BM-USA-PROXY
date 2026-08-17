"""state_cities — which city a state is sold as

The client organises their farm by state and writes it into each connection's name
(`att113_NV`). iproxy exposes no group or state field over the API, and the exit IP's real
city is not what they want to advertise: Las Vegas is a market, Rolling Meadows is not.

So the mapping is theirs to keep, one row per state, editable in the console. Nine rows for
a farm of 2000 phones, versus 2000 descriptions filled in by hand — which is the reason
this exists rather than reading a per-device field.

Seeded with the nine states the client sells today. They own the list from here.

Revision ID: 0023_state_cities
Revises: 0022_pool_alert_repeat_setting
Create Date: 2026-08-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_state_cities"
down_revision: str | None = "0022_pool_alert_repeat_setting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED = [
    ("WA", "Seattle"),
    ("CA", "Los Angeles"),
    ("NV", "Las Vegas"),
    ("OR", "Portland"),
    ("CO", "Denver"),
    ("AZ", "Phoenix"),
    ("TX", "Dallas"),
    ("FL", "Miami"),
    ("IL", "Chicago"),
]


def upgrade() -> None:
    op.create_table(
        "state_cities",
        sa.Column("state_code", sa.Text(), nullable=False),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["admin_users.id"]),
        sa.PrimaryKeyConstraint("state_code"),
    )
    # Seeded here rather than in scripts/seed.py: production already has its tables, so that
    # script never runs against it and the client would open an empty screen.
    op.bulk_insert(
        sa.table(
            "state_cities",
            sa.column("state_code", sa.Text),
            sa.column("city", sa.Text),
        ),
        [{"state_code": code, "city": city} for code, city in _SEED],
    )


def downgrade() -> None:
    op.drop_table("state_cities")

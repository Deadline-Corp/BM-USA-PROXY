"""users.referral_clicks — how many times somebody opened this person's referral link

The console has always shown a "Total clicks" card and it has always read zero, because a
click was never recorded anywhere: a /start carrying a referral code either bound the
newcomer to their referrer or did nothing at all, and either way left no trace. Without it
the referral programme can only be judged by conversions, with no idea how many people it
put in front of the door.

Counted on the referrer, not in a table of events: the card wants one number per person,
and a row per click would be a time series nobody has asked for.

Revision ID: 0011_referral_clicks
Revises: 0010_admin_telegram
Create Date: 2026-08-13
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_referral_clicks"
down_revision: str | None = "0010_admin_telegram"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("referral_clicks", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "referral_clicks")

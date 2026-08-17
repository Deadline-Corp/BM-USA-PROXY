"""users.handle_checked_at — when Telegram was last asked for this person's handle

A visit to the bot or the mini app updates the handle from the data Telegram attaches to
the request, and that data is cached by the Telegram client: measured 2026-08-17, a client
who had renamed themselves hours earlier still arrived as their old handle, while getChat
answered with the new one immediately.

So the handle is also refreshed in the background, oldest check first, and this column is
what "oldest" means. NULL sorts first, so every existing row is picked up on the first pass.

Revision ID: 0024_user_handle_checked_at
Revises: 0023_state_cities
Create Date: 2026-08-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_user_handle_checked_at"
down_revision: str | None = "0023_state_cities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("handle_checked_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "handle_checked_at")

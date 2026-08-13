"""admin_users: telegram_username + telegram_user_id — the second factor's channel

Login is getting a one-time code delivered by the bot, so an admin account needs to point
at a Telegram account. Two columns rather than one, because a @handle is not an address:
the Bot API cannot turn a username into a chat for a private individual, and a bot may not
message anyone who has not started it. So the owner writes the handle they know, and the
numeric id — the only thing a message can actually be sent to — is bound when that person
opens the bot and presses Start.

`telegram_user_id` is unique: two admin accounts must not resolve to the same inbox, or a
code minted for one would be delivered to the other.

Revision ID: 0010_admin_telegram
Revises: 0009_admin_session_epoch
Create Date: 2026-08-13
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_admin_telegram"
down_revision: str | None = "0009_admin_session_epoch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("admin_users", sa.Column("telegram_username", sa.Text(), nullable=True))
    op.add_column("admin_users", sa.Column("telegram_user_id", sa.BigInteger(), nullable=True))
    op.create_index(
        "uq_admin_telegram_user", "admin_users", ["telegram_user_id"], unique=True,
        postgresql_where=sa.text("telegram_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_admin_telegram_user", table_name="admin_users")
    op.drop_column("admin_users", "telegram_user_id")
    op.drop_column("admin_users", "telegram_username")

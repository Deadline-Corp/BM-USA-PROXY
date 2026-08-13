"""admin_users.deleted_at — deleting an account without erasing who did what

A console account is referenced by ten tables, and three screens print its name: the audit
log, the client conversation, and publication comments. Dropping the row would make all of
that anonymous — "who revoked this access" would have no answer at exactly the moment
somebody is asking.

So the account goes and the row stays: it disappears from the list, cannot sign in, and
gives up its email and Telegram handle so a replacement can take them. What it keeps is its
name, and only so that entries written before it went still say who wrote them.

Revision ID: 0012_admin_delete
Revises: 0011_referral_clicks
Create Date: 2026-08-13
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_admin_delete"
down_revision: str | None = "0011_referral_clicks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("admin_users", sa.Column("deleted_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("admin_users", "deleted_at")

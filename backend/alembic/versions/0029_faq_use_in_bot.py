"""faq_items.use_in_bot — operator-written answers the assistant must use

The assistant knew two kinds of fact: ones hardcoded in the source, and ones derived from
live stock. Neither could be corrected by the people who actually know the answers. Asked
which carriers we work with, it read the pool — which happened to hold only Verizon and
T-Mobile phones — and told a customer we do not work with AT&T, which is untrue.

Existing rows default to true: they are already the answers we give customers in the mini
app, so the assistant giving the same ones is the behaviour anybody would expect.

Revision ID: 0029_faq_use_in_bot
Revises: 0028_connection_reservation
Create Date: 2026-08-20
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_faq_use_in_bot"
down_revision: str | None = "0028_connection_reservation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "faq_items",
        sa.Column("use_in_bot", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("faq_items", "use_in_bot")

"""add conversation_messages (client↔operator thread)

Revision ID: 0004_conversation_messages
Revises: 0003_conn_last_rotated
Create Date: 2026-07-14

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_conversation_messages"
down_revision: str | None = "0003_conn_last_rotated"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("admin_id", sa.BigInteger(), nullable=True),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "direction IN ('in','out')", name=op.f("ck_conversation_messages_direction_valid")
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"], ["admin_users.id"],
            name=op.f("fk_conversation_messages_admin_id_admin_users"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_conversation_messages_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_messages")),
    )
    op.create_index("ix_conv_user", "conversation_messages", ["user_id", sa.text("created_at DESC")])
    op.create_index(
        "ix_conv_unread",
        "conversation_messages",
        ["user_id"],
        postgresql_where=sa.text("direction = 'in' AND read_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_conv_unread", table_name="conversation_messages")
    op.drop_index("ix_conv_user", table_name="conversation_messages")
    op.drop_table("conversation_messages")

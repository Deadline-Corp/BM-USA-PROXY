"""conversation_messages.via_ai — outbound rows the AI assistant wrote

Three kinds of outbound row exist now: an operator's reply, the canned acknowledgement,
and an answer from the AI support assistant. ``admin_id IS NULL`` no longer separates
them, and two places need the distinction — the dossier, which must not credit an
operator with a machine's answer, and the acknowledgement rule, which suppresses itself
after a human or canned reply but must still fire after an AI one.

Revision ID: 0026_conversation_via_ai
Revises: 0025_access_last_swap_at
Create Date: 2026-08-20
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_conversation_via_ai"
down_revision: str | None = "0025_access_last_swap_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_messages",
        sa.Column("via_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("conversation_messages", "via_ai")

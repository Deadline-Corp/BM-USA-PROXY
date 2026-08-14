"""app_settings: seed the ops_alert_chats key so the field appears in the console

Operator alerts (a client writing to the bot, a reseller enquiry, low stock, the nightly
reconciliation) went to a single chat fixed at deploy time. The client wants them in two —
support and the owner's channel — and wants to change that themselves.

Inserted here rather than left to scripts/seed.py because that script only runs against a
fresh database: production already has an app_settings table, so the row would never
appear and the field would never show up in the admin Settings screen.

Empty on purpose: whatever is set here is *added to* OPS_ALERT_CHAT_ID, so an empty value
changes nothing about who is being notified today.

Revision ID: 0019_ops_alert_chats_setting
Revises: 0018_connection_external_holds
Create Date: 2026-08-14
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0019_ops_alert_chats_setting"
down_revision: str | None = "0018_connection_external_holds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app_settings (key, value)
        VALUES ('ops_alert_chats', '""'::jsonb)
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM app_settings WHERE key = 'ops_alert_chats'")

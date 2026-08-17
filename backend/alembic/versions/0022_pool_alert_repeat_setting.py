"""app_settings: seed pool_alert_repeat_hours so the field appears in the console

How often the low-stock alert repeats itself was a constant in the code. It answers a
different question from the check interval — that one is how quickly you hear about a drop,
this one is how often you are reminded while it lasts — and both belong to whoever is
carrying the pager.

Inserted here rather than left to scripts/seed.py because that script only runs against a
fresh database.

Revision ID: 0022_pool_alert_repeat_setting
Revises: 0021_pool_check_interval_setting
Create Date: 2026-08-17
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0022_pool_alert_repeat_setting"
down_revision: str | None = "0021_pool_check_interval_setting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app_settings (key, value)
        VALUES ('pool_alert_repeat_hours', '6'::jsonb)
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM app_settings WHERE key = 'pool_alert_repeat_hours'")

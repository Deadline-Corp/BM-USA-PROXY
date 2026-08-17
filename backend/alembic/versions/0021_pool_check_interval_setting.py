"""app_settings: seed pool_check_interval_minutes so the field appears in the console

How often the low-stock check looks was fixed in the worker's cron schedule, so changing
it meant a redeploy. The job now fires every minute and reads this instead.

Inserted here rather than left to scripts/seed.py because that script only runs against a
fresh database: production already has an app_settings table, so the row would never appear
and the field would never show up in Settings.

Revision ID: 0021_pool_check_interval_setting
Revises: 0020_auto_rotate_min_one_minute
Create Date: 2026-08-17
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0021_pool_check_interval_setting"
down_revision: str | None = "0020_auto_rotate_min_one_minute"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app_settings (key, value)
        VALUES ('pool_check_interval_minutes', '5'::jsonb)
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM app_settings WHERE key = 'pool_check_interval_minutes'")

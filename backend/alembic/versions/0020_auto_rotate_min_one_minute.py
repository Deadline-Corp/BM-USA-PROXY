"""auto-rotation: allow intervals down to one minute

The floor was five minutes, chosen because a rotation reboots the phone's data connection
and the new address takes ~10s to settle. The client wants one minute available — for
scraping-style work a short cycle is the point, and the trade-off (the device spends a
noticeable share of each cycle reconnecting) is theirs to make.

The sweep already runs every minute, so a one-minute interval is as fast as the schedule
can go; anything below that would silently behave like one minute.

Revision ID: 0020_auto_rotate_min_one_minute
Revises: 0019_ops_alert_chats_setting
Create Date: 2026-08-17
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0020_auto_rotate_min_one_minute"
down_revision: str | None = "0019_ops_alert_chats_setting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("auto_rotate_minutes_sane", "accesses", type_="check")
    op.create_check_constraint(
        "auto_rotate_minutes_sane",
        "accesses",
        "auto_rotate_minutes IS NULL OR (auto_rotate_minutes >= 1 "
        "AND auto_rotate_minutes <= 1440)",
    )


def downgrade() -> None:
    # Anything faster than the old floor has to go, or the restored constraint cannot be
    # created. Turning auto-rotation off is the only honest choice for those rows: there
    # is no "nearest allowed value" that keeps a promise the customer set themselves.
    op.execute("UPDATE accesses SET auto_rotate_minutes = NULL WHERE auto_rotate_minutes < 5")
    op.drop_constraint("auto_rotate_minutes_sane", "accesses", type_="check")
    op.create_check_constraint(
        "auto_rotate_minutes_sane",
        "accesses",
        "auto_rotate_minutes IS NULL OR (auto_rotate_minutes >= 5 "
        "AND auto_rotate_minutes <= 1440)",
    )

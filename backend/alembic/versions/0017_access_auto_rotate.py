"""accesses.auto_rotate_minutes — buyer-scheduled IP rotation

NULL means off. A single nullable interval rather than an on/off flag beside a number,
because those two columns can contradict each other and nothing downstream should have to
decide what "enabled, interval 0" means.

The schedule lives on the access, not on the connection: iproxy's own per-connection
ip_change settings would keep rotating the phone after the access ends and would follow it
to whoever is sold that connection next.

Revision ID: 0017_access_auto_rotate
Revises: 0016_access_socks5_and_link
Create Date: 2026-08-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_access_auto_rotate"
down_revision: str | None = "0016_access_socks5_and_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("accesses", sa.Column("auto_rotate_minutes", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "auto_rotate_minutes_sane",
        "accesses",
        "auto_rotate_minutes IS NULL OR (auto_rotate_minutes >= 5 "
        "AND auto_rotate_minutes <= 1440)",
    )


def downgrade() -> None:
    op.drop_constraint("auto_rotate_minutes_sane", "accesses", type_="check")
    op.drop_column("accesses", "auto_rotate_minutes")

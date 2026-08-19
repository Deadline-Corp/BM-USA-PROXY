"""accesses.last_swap_at — the daily swap limit's clock

Swapping used to be capped by the plan's ``max_user_swaps``, a lifetime count. The limit
is now one swap per day per access, which a counter cannot express: it has no notion of
when to reset. NULL means "never swapped", so every access that exists when this lands may
swap immediately — the kinder reading of a limit nobody had been told about yet.

``max_user_swaps`` stays on tariffs. Nothing gates on it now, but dropping a column is a
one-way door and the plan rows still carry the numbers they were saved with.

Revision ID: 0025_access_last_swap_at
Revises: 0024_user_handle_checked_at
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0025_access_last_swap_at"
down_revision: str | None = "0024_user_handle_checked_at"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("accesses", sa.Column("last_swap_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("accesses", "last_swap_at")

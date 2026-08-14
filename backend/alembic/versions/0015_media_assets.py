"""media_assets — one replaceable binary asset: the bot's welcome-image

The container's disk does not survive a Railway deploy, so anything an operator uploads
at runtime has to live in Postgres, not the filesystem, to still be there tomorrow. This
table is deliberately not a general media library — one row today, keyed
'welcome_image' (see app.services.media) — because that is the one replaceable asset the
task called for, not a table of arbitrary uploads.

Shaped like app_settings (text key, updated_by/updated_at) but kept separate from it:
app_settings.value is JSONB, and a coverage-map JPEG does not belong base64-stuffed into
a JSON column next to referral percentages.

Revision ID: 0015_media_assets
Revises: 0014_drop_connection_geo
Create Date: 2026-08-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_media_assets"
down_revision: str | None = "0014_drop_connection_geo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["admin_users.id"]),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("media_assets")

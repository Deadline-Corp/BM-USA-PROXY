"""admin_users.sessions_valid_from — make "change the password" mean "sign them out"

Changing an operator's password did not end the sessions they already had. The refresh
cookie lives 14 days and rotates itself, so someone who left the company kept working
access for up to two weeks after their password was changed — including the ability to
edit the receiving wallet addresses. Deactivating the account did not help either: the
check only ran on new logins.

One timestamp fixes both. Every token carries `iat`; a token issued before this moment is
refused. Setting it to now() is therefore "end every session this account has", and it is
set whenever the password changes or the account is deactivated.

NULL means "never revoked", which is every account that exists today — nobody is signed
out by this migration running.

Revision ID: 0009_admin_session_epoch
Revises: 0008_access_vpn_configs
Create Date: 2026-08-13
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_admin_session_epoch"
down_revision: str | None = "0008_access_vpn_configs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "admin_users",
        sa.Column("sessions_valid_from", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("admin_users", "sessions_valid_from")

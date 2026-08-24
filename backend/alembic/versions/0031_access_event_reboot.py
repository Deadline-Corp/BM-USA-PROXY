"""access_events.type gains 'reboot'

The buyer can now ask for the phone behind their port to be restarted, and that has to be
recorded on the access like every other thing done to it. The type column is a whitelist,
so writing a new kind of event without widening it fails at the last moment — the customer
presses Reboot, the command reaches iproxy, and the transaction rolls back on the log line.

Revision ID: 0031_access_event_reboot
Revises: 0030_order_partially_refunded
Create Date: 2026-08-24
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0031_access_event_reboot"
down_revision: str | None = "0030_order_partially_refunded"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = (
    "issued",
    "rotate_ip",
    "extended",
    "expiry_warning",
    "expired",
    "revoked",
    "reissued",
    "config_delivered",
    "provision_failed",
)
_NEW = (*_TYPES, "reboot")


def _rewrite(values: tuple[str, ...]) -> None:
    # Bare name — the alembic naming convention prepends ``ck_access_events_`` itself.
    op.drop_constraint("type_valid", "access_events", type_="check")
    joined = ",".join(f"'{v}'" for v in values)
    op.create_check_constraint("type_valid", "access_events", f"type IN ({joined})")


def upgrade() -> None:
    _rewrite(_NEW)


def downgrade() -> None:
    # The history of a reboot cannot be expressed in the old vocabulary, and inventing a
    # different type for it would put a wrong entry in a customer's timeline. Dropping the
    # rows is the honest reversal: the event log is a record, not a source of truth for
    # anything the system decides.
    op.execute("DELETE FROM access_events WHERE type = 'reboot'")
    _rewrite(_TYPES)

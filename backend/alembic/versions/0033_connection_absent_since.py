"""record when a connection stopped being listed in the iproxy account

The sync has been able to notice a phone disappearing from the account since
0031's release — it marked the row offline and wrote a sentence into
`health_note`. That was enough to stop it being sold and not enough to stop it
being *shown*: the console listed 21 phones while the client's iproxy account
held 19, and the two extra were ones they had removed weeks earlier.

A sentence in a free-text field is also the wrong place for the fact. Nothing can
filter on it without matching on prose, and `health_note` is about the health of a
device that exists, not about a device that does not. So the fact gets a column,
and the sentence goes away — the migration converts the rows that carry it.

`absent_since` rather than a boolean, because "since when" is the question an
operator asks next, and a timestamp answers both.

Revision ID: 0033_connection_absent_since
Revises: 0032_promo_codes
Create Date: 2026-09-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_connection_absent_since"
down_revision: str | None = "0032_promo_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Exactly what services/provisioning/sync.py used to write. Matched literally because it
# is the only way to find these rows, which is itself the argument for the column.
_OLD_NOTE = "Not in the iproxy account any more — deleted or moved."


def upgrade() -> None:
    op.add_column("connections", sa.Column("absent_since", sa.DateTime(timezone=True)))
    # Partial: the column is NULL for almost every row, and every query that uses it asks
    # for one side or the other.
    op.create_index(
        "ix_connections_absent",
        "connections",
        ["absent_since"],
        postgresql_where=sa.text("absent_since IS NOT NULL"),
    )
    # Carry the rows the old mechanism had already found. `synced_at` is when the sync last
    # touched them, which for a vanished phone is the pass that found it missing — closer
    # to the truth than `now()` and never later than it.
    op.execute(
        sa.text(
            """
            UPDATE connections
               SET absent_since = COALESCE(synced_at, now()),
                   health_note = NULL
             WHERE health_note = :note
            """
        ).bindparams(note=_OLD_NOTE)
    )
    # The template that warns a customer before their access ends is no longer fixed at 24
    # hours — see services/maintenance.py — so its name no longer describes it. Carry over
    # an operator's edited text if there is one; the default follows the code.
    op.execute(
        """
        UPDATE app_settings
           SET key = 'notify_texts:access_expiring_soon'
         WHERE key = 'notify_texts:access_expiring_24h'
           AND NOT EXISTS (
             SELECT 1 FROM app_settings s2 WHERE s2.key = 'notify_texts:access_expiring_soon')
        """
    )


    # Anything already queued under the old name would find no template after this deploy
    # and be dropped as "skipped" — one customer, one missed warning, silently. Every such
    # row was queued by the flat 24-hour rule, so "24 hours" is not a guess about it.
    op.execute(
        """
        UPDATE notifications_outbox
           SET template_code = 'access_expiring_soon',
               payload = COALESCE(payload, '{}'::jsonb) || '{"left": "24 hours"}'::jsonb
         WHERE template_code = 'access_expiring_24h'
           AND status = 'pending'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE app_settings
           SET key = 'notify_texts:access_expiring_24h'
         WHERE key = 'notify_texts:access_expiring_soon'
           AND NOT EXISTS (
             SELECT 1 FROM app_settings s2 WHERE s2.key = 'notify_texts:access_expiring_24h')
        """
    )
    op.execute(
        sa.text(
            "UPDATE connections SET health_note = :note WHERE absent_since IS NOT NULL"
        ).bindparams(note=_OLD_NOTE)
    )
    op.drop_index("ix_connections_absent", table_name="connections")
    op.drop_column("connections", "absent_since")

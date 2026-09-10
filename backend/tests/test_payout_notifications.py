"""What the outbox does with a payout approval, and with a code that has no text.

Found on production 2026-09-10. `payout_approved` sat in the template whitelist and was
enqueued by the approve endpoint on every approval, but had no entry in DEFAULT_TEXTS.
`render()` returns None when there is no template, `deliver_pending` marks such a row
`skipped`, and so all four approvals this project has ever made were dropped without a
word: the partner was told "in the queue" and then heard nothing until the coins arrived.
Nothing alerted, because a skipped row looks like a decision rather than a failure.

`sent_at` was never written either — 143 rows read status='sent' with sent_at NULL — so
the one query that could have exposed the silence ("what has this outbox actually sent")
answered "nothing, ever".

The last test here is the one that matters after today: it holds the whitelist and the
texts together, so the next code added to one without the other fails in CI rather than in
a partner's chat.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.bot.notifier import DEFAULT_TEXTS, deliver_pending
from app.models import NotificationOutbox, User
from app.services.notifications import TEMPLATES, enqueue
from sqlalchemy import select


class _StubBot:
    """Records what would have gone to Telegram."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **_kw) -> None:
        self.sent.append((chat_id, text))


async def _partner(session) -> User:
    user = User(tg_user_id=990_001, tg_username="partner", referral_code="PAYOUTQ1")
    session.add(user)
    await session.flush()
    return user


async def test_an_approved_payout_reaches_the_partner(session) -> None:
    """The exact payload the approve endpoint sends — id and amount, nothing else."""
    user = await _partner(session)
    await enqueue(
        session,
        user_id=user.id,
        template_code="payout_approved",
        payload={"payout_id": 4, "amount_usd": 5.29},
    )
    await session.flush()

    bot = _StubBot()
    result = await deliver_pending(session, bot)
    await session.flush()

    assert result == {"sent": 1, "failed": 0, "blocked": 0}
    row = await session.scalar(select(NotificationOutbox))
    assert row is not None and row.status == "sent"
    assert len(bot.sent) == 1
    chat_id, text = bot.sent[0]
    assert chat_id == user.tg_user_id
    # The amount has to survive into the message: a payout notice without the number is
    # the failure this whole file is about, one step later.
    assert "5.29" in text


async def test_a_delivered_row_records_when_it_went_out(session) -> None:
    user = await _partner(session)
    await enqueue(session, user_id=user.id, template_code="access_expired", payload={})
    await session.flush()

    before = datetime.now(UTC)
    await deliver_pending(session, _StubBot())
    await session.flush()

    row = await session.scalar(select(NotificationOutbox))
    assert row is not None and row.status == "sent"
    assert row.sent_at is not None, "a row marked sent with no timestamp is unauditable"
    assert row.sent_at >= before


async def test_a_code_with_no_text_is_skipped_and_never_stamped(session) -> None:
    """The other half of the fix: skipping is still what happens when there IS no text.

    Without this, the first test could pass on a `render()` that had stopped refusing
    anything at all — which would send "Your payout of $ was approved" the day a payload
    lost its amount.
    """
    user = await _partner(session)
    await enqueue(session, user_id=user.id, template_code="not_a_real_template", payload={})
    await session.flush()

    bot = _StubBot()
    result = await deliver_pending(session, bot)
    await session.flush()

    assert result == {"sent": 0, "failed": 0, "blocked": 0}
    assert bot.sent == []
    row = await session.scalar(select(NotificationOutbox))
    assert row is not None and row.status == "skipped"
    assert row.sent_at is None


async def test_a_placeholder_with_nothing_behind_it_is_still_refused(session) -> None:
    """`payout_paid` needs a tx hash. A payload without one must not send "Tx: "."""
    user = await _partner(session)
    await enqueue(
        session,
        user_id=user.id,
        template_code="payout_paid",
        payload={"amount_usd": 5.29},  # no tx_hash
    )
    await session.flush()

    bot = _StubBot()
    await deliver_pending(session, bot)
    await session.flush()

    assert bot.sent == []
    row = await session.scalar(select(NotificationOutbox))
    assert row is not None and row.status == "skipped"


def test_every_whitelisted_template_has_a_text() -> None:
    """The invariant that would have caught this before it shipped.

    A code in TEMPLATES with no DEFAULT_TEXTS entry is a message the product promises,
    enqueues, and silently discards; it also shows on the admin Notifications screen as an
    empty row, which reads as "no text set" rather than "this will never send".
    """
    assert set(DEFAULT_TEXTS) == TEMPLATES, (
        "TEMPLATES and DEFAULT_TEXTS disagree — "
        f"no text: {sorted(TEMPLATES - set(DEFAULT_TEXTS))}, "
        f"not whitelisted: {sorted(set(DEFAULT_TEXTS) - TEMPLATES)}"
    )

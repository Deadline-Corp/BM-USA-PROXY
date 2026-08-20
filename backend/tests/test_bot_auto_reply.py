"""Writing to the bot gets an answer back.

Until this existed, a client messaging the bot got silence: the message was stored and
the operator chats were pinged, but nothing returned to the person who wrote it, so the
only evidence available to them was that nothing happened.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest_asyncio
from app.bot.handlers import conversation
from app.models import ConversationMessage, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker


class _StubUser:
    id = 880011
    username = "writer"
    first_name = "Writer"
    last_name = None
    language_code = "en"


class _StubMessage:
    """Only what the handler touches: who sent it, what it says, and answer()."""

    def __init__(self, text: str, message_id: int = 1) -> None:
        self.text = text
        self.message_id = message_id
        self.from_user = _StubUser()
        self.answers: list[str] = []

    async def answer(self, text: str, **_: Any) -> None:
        self.answers.append(text)


@pytest_asyncio.fixture
async def bot_db(engine, monkeypatch):
    """Point the handler's own SessionFactory at the test database."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(conversation, "SessionFactory", maker)

    async def no_ops(*_args, **_kwargs):
        return None

    # The operator ping is a separate concern with its own failure handling; this suite is
    # about what the client receives.
    monkeypatch.setattr(conversation.ops_alerts, "notify_ops", no_ops)
    return maker


async def _thread(maker) -> list[ConversationMessage]:
    async with maker() as s:
        return list(
            await s.scalars(
                select(ConversationMessage).order_by(ConversationMessage.created_at.asc())
            )
        )


async def test_a_plain_message_is_answered_and_the_reply_is_on_the_thread(bot_db) -> None:
    message = _StubMessage("do you have Chicago on AT&T?")

    await conversation.capture_message(message)  # type: ignore[arg-type]

    assert message.answers == [conversation._ACK_TEXT]
    rows = await _thread(bot_db)
    assert [(r.direction, r.body) for r in rows] == [
        ("in", "do you have Chicago on AT&T?"),
        ("out", conversation._ACK_TEXT),
    ]
    # Nobody typed the reply, and the dossier needs to be able to say so.
    assert rows[1].admin_id is None


async def test_three_messages_in_a_row_get_one_reply(bot_db) -> None:
    """The rule that keeps the acknowledgement from becoming an echo."""
    for i, text in enumerate(("hi", "are you there?", "hello?")):
        await conversation.capture_message(_StubMessage(text, message_id=i))  # type: ignore[arg-type]

    rows = await _thread(bot_db)
    assert [r.direction for r in rows] == ["in", "out", "in", "in"]


async def test_the_reply_comes_back_once_the_cooldown_has_passed(bot_db) -> None:
    await conversation.capture_message(_StubMessage("first"))  # type: ignore[arg-type]

    async with bot_db() as s:
        ack = await s.scalar(
            select(ConversationMessage).where(ConversationMessage.direction == "out")
        )
        assert ack is not None
        ack.created_at = datetime.now(UTC) - conversation._ACK_COOLDOWN - timedelta(minutes=1)
        await s.commit()

    later = _StubMessage("still waiting", message_id=2)
    await conversation.capture_message(later)  # type: ignore[arg-type]

    assert later.answers == [conversation._ACK_TEXT]


async def test_an_operator_reply_holds_the_bot_back(bot_db) -> None:
    """A human is already talking to this person; the canned line would talk over them."""
    await conversation.capture_message(_StubMessage("hello"))  # type: ignore[arg-type]

    async with bot_db() as s:
        user = await s.scalar(select(User).where(User.tg_user_id == _StubUser.id))
        assert user is not None
        s.add(
            ConversationMessage(
                user_id=user.id, direction="out", body="Chicago is free right now."
            )
        )
        await s.commit()

    reply = _StubMessage("great, I will take it", message_id=3)
    await conversation.capture_message(reply)  # type: ignore[arg-type]

    assert reply.answers == []


async def test_the_wording_follows_the_operators_own_text(bot_db) -> None:
    """The line is editable on the Notifications screen like every other bot message.

    It was a constant in the source until an operator asked to change it, which meant a
    deploy to reword a sentence — and left the bot answering in English while the
    assistant beside it answered in the client's own language.
    """
    from app.services import settings as settings_svc

    custom = "Спасибо за сообщение! Оператор скоро ответит."
    async with bot_db() as s:
        await settings_svc.set_value(s, f"notify_texts:{conversation.ACK_TEMPLATE}", custom)
        await s.commit()

    message = _StubMessage("здравствуйте")
    await conversation.capture_message(message)  # type: ignore[arg-type]

    assert message.answers == [custom]
    rows = await _thread(bot_db)
    # Sent and recorded must agree — the dossier is what an operator reads to find out
    # what this client was actually told.
    assert rows[-1].body == custom


async def test_a_blank_override_falls_back_to_the_built_in_text(bot_db) -> None:
    """Clearing the field restores the default rather than silencing the bot.

    Same rule as the rest of the templates. Without it, an operator emptying the box to
    "turn it off" would put the bot back to answering nothing at all, which is the exact
    silence this reply was added to fix.
    """
    from app.services import settings as settings_svc

    async with bot_db() as s:
        await settings_svc.set_value(s, f"notify_texts:{conversation.ACK_TEMPLATE}", "")
        await s.commit()

    message = _StubMessage("hello")
    await conversation.capture_message(message)  # type: ignore[arg-type]

    assert message.answers == [conversation._ACK_TEXT]


async def test_a_failed_send_records_no_reply(bot_db) -> None:
    """Otherwise the thread would claim the client was answered when they were not."""

    class _Silenced(_StubMessage):
        async def answer(self, text: str, **_: Any) -> None:
            raise RuntimeError("telegram said no")

    await conversation.capture_message(_Silenced("hello"))  # type: ignore[arg-type]

    rows = await _thread(bot_db)
    assert [r.direction for r in rows] == ["in"]

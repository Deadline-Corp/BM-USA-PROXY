"""The assistant answers the easy questions and gets out of the way for everything else.

Two things are being pinned here, and the second matters more than the first: that a
plausible answer reaches the client, and that *every* way this layer can fail — switched
off, no key, a timeout, a refusal, a send that bounces, an operator already talking — ends
in the behaviour the bot had before it existed. The client's message is committed before
the assistant is consulted, so no path here can lose it; what these tests defend is that no
path can silently swallow the *reply* either.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest_asyncio
from app.bot.handlers import conversation
from app.models import AdminUser, ConversationMessage, Tariff, User
from app.services import ai_support
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker


class _StubUser:
    id = 880022
    username = "asker"
    first_name = "Asker"
    last_name = None
    language_code = "ru"


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
    """Handler wired to the test database, with both outward channels captured.

    `notify_ops` and `notify_ai_answered` are recorded rather than stubbed away: which of
    the two fired — the full operator fan-out or the single courtesy copy — is the
    observable difference between escalating and answering, so the tests below assert on it.
    """
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(conversation, "SessionFactory", maker)

    ops_calls: list[str] = []
    ping_calls: list[tuple[str, str]] = []

    async def record_ops(_session, text):
        ops_calls.append(text)

    async def record_ping(_session, _cfg, _who, question, answer):
        ping_calls.append((question, answer))

    monkeypatch.setattr(conversation.ops_alerts, "notify_ops", record_ops)
    monkeypatch.setattr(conversation.ai_support, "notify_ai_answered", record_ping)
    maker.ops_calls = ops_calls  # type: ignore[attr-defined]
    maker.ping_calls = ping_calls  # type: ignore[attr-defined]
    return maker


def _enable(monkeypatch, *, ping_ops: bool = True) -> None:
    """Turn the assistant on without touching the settings table."""

    async def cfg(_session):
        return ai_support.AiSupportConfig(
            enabled=True, ping_ops=ping_ops, ping_chat="@usproxy_support"
        )

    monkeypatch.setattr(conversation.ai_support, "get_config", cfg)


def _answers(monkeypatch, reply: str | None) -> list[str]:
    """Make the assistant return `reply`; returns the list of questions it was asked."""
    seen: list[str] = []

    async def try_answer(_session, _user, text):
        seen.append(text)
        return reply

    monkeypatch.setattr(conversation.ai_support, "try_answer", try_answer)
    return seen


async def _thread(maker) -> list[ConversationMessage]:
    async with maker() as s:
        return list(
            await s.scalars(
                select(ConversationMessage).order_by(ConversationMessage.created_at.asc())
            )
        )


async def _user(maker) -> User:
    async with maker() as s:
        user = await s.scalar(select(User).where(User.tg_user_id == _StubUser.id))
        assert user is not None
        return user


# ── the switch ────────────────────────────────────────────────────────────


async def test_switched_off_behaves_exactly_as_before(bot_db, monkeypatch) -> None:
    """The default. Deploying this code must change nothing until somebody opts in."""
    asked = _answers(monkeypatch, "an answer nobody should see")
    message = _StubMessage("сколько стоит месяц?")

    await conversation.capture_message(message)  # type: ignore[arg-type]

    assert asked == []  # the assistant was never consulted
    assert message.answers == [conversation._ACK_TEXT]
    assert len(bot_db.ops_calls) == 1


# ── answering ─────────────────────────────────────────────────────────────


async def test_an_answered_question_reaches_the_client_and_stops_there(
    bot_db, monkeypatch
) -> None:
    _enable(monkeypatch)
    _answers(monkeypatch, "Месяц стоит $85.")

    message = _StubMessage("сколько стоит месяц?")
    await conversation.capture_message(message)  # type: ignore[arg-type]

    assert message.answers == ["Месяц стоит $85."]
    rows = await _thread(bot_db)
    assert [(r.direction, r.body) for r in rows] == [
        ("in", "сколько стоит месяц?"),
        ("out", "Месяц стоит $85."),
    ]
    # Machine-written, and the dossier has to be able to say so.
    assert rows[1].via_ai is True
    assert rows[1].admin_id is None
    # Nothing for a human to pick up, so nobody is paged and no promise of one is made.
    assert bot_db.ops_calls == []
    assert conversation._ACK_TEXT not in message.answers


async def test_the_support_chat_gets_a_copy_only_while_the_toggle_is_on(
    bot_db, monkeypatch
) -> None:
    """The second switch exists so the courtesy copies can be turned off on their own."""
    _enable(monkeypatch, ping_ops=True)
    _answers(monkeypatch, "Поддерживаются Socks5 и HTTP.")
    await conversation.capture_message(_StubMessage("какие протоколы?"))  # type: ignore[arg-type]
    assert len(bot_db.ping_calls) == 1
    assert bot_db.ping_calls[0] == ("какие протоколы?", "Поддерживаются Socks5 и HTTP.")

    _enable(monkeypatch, ping_ops=False)
    await conversation.capture_message(_StubMessage("а ещё?", message_id=2))  # type: ignore[arg-type]
    assert len(bot_db.ping_calls) == 1  # unchanged — the second answer was not copied


# ── handing over ──────────────────────────────────────────────────────────


async def test_a_refusal_escalates_exactly_like_before(bot_db, monkeypatch) -> None:
    """ESCALATE reaches the handler as None; the client must still be acknowledged."""
    _enable(monkeypatch)
    _answers(monkeypatch, None)

    message = _StubMessage("я оплатил, доступа нет")
    await conversation.capture_message(message)  # type: ignore[arg-type]

    assert message.answers == [conversation._ACK_TEXT]
    assert len(bot_db.ops_calls) == 1
    rows = await _thread(bot_db)
    assert [r.via_ai for r in rows] == [False, False]


async def test_a_broken_assistant_escalates(bot_db, monkeypatch) -> None:
    """A timeout or a 500 must be indistinguishable, from the outside, from a refusal."""
    _enable(monkeypatch)

    async def boom(_session, _user, _text):
        raise RuntimeError("gateway is down")

    # try_answer swallows its own failures; this asserts the handler survives one that
    # escapes anyway — a bug there would take the whole message down with it.
    monkeypatch.setattr(conversation.ai_support, "try_answer", boom)

    message = _StubMessage("какие города есть?")
    try:
        await conversation.capture_message(message)  # type: ignore[arg-type]
    except RuntimeError:
        raise AssertionError("a failing assistant must not take the handler down") from None

    assert message.answers == [conversation._ACK_TEXT]
    assert len(bot_db.ops_calls) == 1


async def test_a_send_that_bounces_falls_back_to_the_operator(bot_db, monkeypatch) -> None:
    """Otherwise the thread claims an answer the client never received."""
    _enable(monkeypatch)
    _answers(monkeypatch, "Города: Chicago, Miami.")

    class _Silenced(_StubMessage):
        async def answer(self, text: str, **_: Any) -> None:
            raise RuntimeError("telegram said no")

    await conversation.capture_message(_Silenced("какие города?"))  # type: ignore[arg-type]

    rows = await _thread(bot_db)
    assert [r.direction for r in rows] == ["in"]  # no row claiming we answered
    assert len(bot_db.ops_calls) == 1  # a human picks it up instead


async def test_the_assistant_stays_out_of_a_live_operator_conversation(
    bot_db, monkeypatch
) -> None:
    """A human is mid-thread; answering over the top of them is worse than silence."""
    _enable(monkeypatch)
    asked = _answers(monkeypatch, "should never be sent")

    await conversation.capture_message(_StubMessage("привет"))  # type: ignore[arg-type]
    asked.clear()

    user = await _user(bot_db)
    async with bot_db() as s:
        admin = AdminUser(
            email="op@bmusproxy.local",
            display_name="Operator",
            password_hash="x",
            role="owner",
            is_active=True,
        )
        s.add(admin)
        await s.flush()
        s.add(
            ConversationMessage(
                user_id=user.id,
                direction="out",
                body="Здравствуйте, смотрю ваш заказ.",
                admin_id=admin.id,
            )
        )
        await s.commit()

    await conversation.capture_message(_StubMessage("спасибо!", message_id=2))  # type: ignore[arg-type]

    assert asked == []  # not consulted at all
    assert len(bot_db.ops_calls) == 1  # the operator hears about the reply


# ── the acknowledgement rule ──────────────────────────────────────────────


async def test_an_answer_does_not_swallow_the_next_escalations_acknowledgement(
    bot_db, monkeypatch
) -> None:
    """The reason `via_ai` exists at all.

    Answer a simple question, then ask a hard one a minute later. The acknowledgement
    suppresses itself after a recent outbound message — and counting the AI's answer there
    left the escalation with no reply to the client whatsoever: no answer, no "an operator
    will get back to you", nothing.
    """
    _enable(monkeypatch)
    _answers(monkeypatch, "Месяц стоит $85.")
    await conversation.capture_message(_StubMessage("сколько стоит?"))  # type: ignore[arg-type]

    _answers(monkeypatch, None)
    escalated = _StubMessage("я перевёл деньги, где доступ?", message_id=2)
    await conversation.capture_message(escalated)  # type: ignore[arg-type]

    assert escalated.answers == [conversation._ACK_TEXT]


async def test_a_canned_acknowledgement_still_suppresses_the_next_one(
    bot_db, monkeypatch
) -> None:
    """The carve-out above is for AI rows only — the original throttle is untouched."""
    _enable(monkeypatch)
    _answers(monkeypatch, None)

    first = _StubMessage("вопрос один")
    second = _StubMessage("вопрос два", message_id=2)
    await conversation.capture_message(first)  # type: ignore[arg-type]
    await conversation.capture_message(second)  # type: ignore[arg-type]

    assert first.answers == [conversation._ACK_TEXT]
    assert second.answers == []


# ── the service in isolation ──────────────────────────────────────────────


async def test_without_a_key_the_service_never_reaches_the_network(
    session, monkeypatch
) -> None:
    """Deploying before the client's API key exists must be safe.

    The key is cleared explicitly rather than assumed absent: a developer with one in
    their own .env would otherwise turn this test into a live billed API call.
    """
    user = User(tg_user_id=990001, first_name="NoKey", referral_code="nokey01")
    session.add(user)
    await session.commit()

    monkeypatch.setattr(ai_support.settings, "ai_support_api_key", None)
    monkeypatch.setattr(ai_support, "_client", None)

    assert await ai_support.try_answer(session, user, "сколько стоит?") is None


async def test_history_is_alternating_turns_the_api_will_accept(session) -> None:
    """Three lines in a row from one person is the shape the API rejects."""
    user = User(tg_user_id=990002, first_name="Chatty", referral_code="chatty01")
    session.add(user)
    await session.commit()

    base = datetime.now(UTC) - timedelta(minutes=10)
    for i, (direction, body) in enumerate(
        [
            ("out", "leading assistant row"),  # dropped: a thread cannot open on one
            ("in", "привет"),
            ("in", "вы работаете?"),  # merged with the line above
            ("out", "Да, работаем."),
            ("in", "сколько стоит?"),
        ]
    ):
        session.add(
            ConversationMessage(
                user_id=user.id,
                direction=direction,
                body=body,
                created_at=base + timedelta(seconds=i),
            )
        )
    await session.commit()

    turns = await ai_support._history(session, user.id)

    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[0]["content"] == "привет\nвы работаете?"
    assert turns[-1]["content"] == "сколько стоит?"


async def test_the_fact_sheet_quotes_the_live_catalogue(session) -> None:
    """Prices reach the prompt from the tariff table, never from a second copy in code.

    The operator edits pricing in the console; a fact sheet with its own "$85" in it is one
    that eventually contradicts the app the customer is being pointed at.
    """
    session.add(
        Tariff(
            code="t-ai-facts",
            name="Monthly",
            kind="auto",
            auto_issue=True,
            duration_minutes=60 * 24 * 30,
            price_usd=85,
            is_active=True,
        )
    )
    await session.commit()

    facts = await ai_support.build_facts(session)

    assert "Monthly" in facts
    assert "$85.00" in facts
    assert "30 days" in facts

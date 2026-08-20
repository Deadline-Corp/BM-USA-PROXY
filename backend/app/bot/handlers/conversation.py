"""Catch-all inbound-message capture.

Stores any free-text DM a client sends the bot into the conversation thread so
operators can read + reply from the admin, answers the client so they know it landed,
and (best-effort) pings the operator alert chat. Registered AFTER the command router so
/start, /app, /help win first; the ``~F.text.startswith("/")`` guard keeps stray
slash-commands out of the thread.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.notifier import DEFAULT_TEXTS, render
from app.core.db import SessionFactory
from app.core.logging import log
from app.models import ConversationMessage
from app.services import ai_support, ops_alerts
from app.services.users import upsert_from_telegram

router = Router(name="conversation")

# What the client sees the moment their message lands. Until this existed, writing to the
# bot looked exactly like writing into a void: the message was stored and the operators
# were pinged, but nothing came back, so the only signal available to the person was
# silence — which reads as "nobody is there".
#
# The wording is operator-editable on the Notifications screen like every other message
# the bot sends; this constant is only the built-in default it falls back to. Blanking the
# field restores this text rather than silencing the bot — same rule as the other templates.
ACK_TEMPLATE = "bot_auto_reply"
_ACK_TEXT = DEFAULT_TEXTS[ACK_TEMPLATE]

# How long one acknowledgement covers. Somebody typing three lines in a row gets one
# reply, not three, and somebody already mid-conversation with a human is not told again
# that an operator will be in touch. Any outbound message resets it, the operator's own
# replies included — the promise has already been kept by then.
_ACK_COOLDOWN = timedelta(hours=1)


async def _ack_is_due(session: AsyncSession, user_id: int) -> bool:
    """Whether to tell this client an operator is coming.

    The promise is the last thing said to them that a person stands behind — a canned
    acknowledgement or an operator's own reply. An AI answer is not one: it answers the
    question that was asked and says nothing about a human.

    Two rules, and the second exists because of a real silence on production. Somebody had
    a six-message conversation with the assistant, said something abusive, and heard
    nothing at all for the next six minutes — the assistant refused (correctly), operators
    were alerted (correctly), and the acknowledgement was suppressed by a promise made
    forty minutes earlier, before that conversation had even started. From the outside the
    bot simply went mute mid-chat. So a promise is spent once the bot has answered
    something after it: whatever it covered, it did not cover this.
    """
    now = datetime.now(UTC)

    def _last(via_ai: bool) -> Select[tuple[datetime]]:
        return select(func.max(ConversationMessage.created_at)).where(
            ConversationMessage.user_id == user_id,
            ConversationMessage.direction == "out",
            ConversationMessage.via_ai.is_(via_ai),
        )

    last_promise = await session.scalar(_last(False))
    if last_promise is None or now - last_promise >= _ACK_COOLDOWN:
        return True
    # Still inside the hour — but if the assistant has spoken since, the conversation has
    # moved on and this refusal needs a promise of its own. Three refusals in a row still
    # produce one, because the first one's acknowledgement then becomes the newest promise.
    last_answer = await session.scalar(_last(True))
    return last_answer is not None and last_answer > last_promise


async def _starts_a_burst(session: AsyncSession, user_id: int) -> bool:
    """Is this the first message of a run, or a follow-up to one already reported?

    Deliberately "what was the last thing said on this thread" rather than a time window.
    A real reply — an operator's or the assistant's — closes the run, so the next message
    is news again. That keeps the case that matters most: an operator is mid-conversation,
    the client answers them, and the operator hears about it without having to sit
    watching the dossier.

    The canned acknowledgement is invisible here, and has to be: it is our own reflex
    rather than anybody engaging, and counting it closed the run after every single
    message — which paged an operator for all three lines of a burst instead of one.

    The inbound message is already committed by the caller, so the row before it is the
    one being asked about.
    """
    recent = (
        await session.scalars(
            select(ConversationMessage.direction)
            .where(
                ConversationMessage.user_id == user_id,
                ~(
                    (ConversationMessage.direction == "out")
                    & ConversationMessage.admin_id.is_(None)
                    & ConversationMessage.via_ai.is_(False)
                ),
            )
            .order_by(
                ConversationMessage.created_at.desc(), ConversationMessage.id.desc()
            )
            .limit(2)
        )
    ).all()
    return len(recent) < 2 or recent[1] == "out"


async def _operator_active(session: AsyncSession, user_id: int) -> bool:
    """Has a human written to this client recently?

    The assistant stays out of a conversation an operator is already having: answering
    over the top of a person mid-thread is worse than saying nothing, and the operator
    has context the model does not.
    """
    last_human = await session.scalar(
        select(func.max(ConversationMessage.created_at)).where(
            ConversationMessage.user_id == user_id,
            ConversationMessage.direction == "out",
            ConversationMessage.admin_id.is_not(None),
        )
    )
    return last_human is not None and datetime.now(UTC) - last_human < _ACK_COOLDOWN


def _identity(message: Message) -> dict[str, Any]:
    u = message.from_user
    return {
        "tg_user_id": u.id if u else 0,
        "tg_username": u.username if u else None,
        "first_name": u.first_name if u else None,
        "last_name": u.last_name if u else None,
        "lang": (u.language_code if u else None) or "en",
    }


async def _deliver_ai_answer(
    message: Message,
    *,
    user_id: int,
    who: str,
    question: str,
    answer: str,
    cfg: ai_support.AiSupportConfig,
) -> bool:
    """Send an AI answer and record it. False means "escalate after all".

    Sent before it is recorded, for the same reason the acknowledgement below is: a reply
    that never reached Telegram must not leave a row on the thread claiming it did.
    """
    try:
        # parse_mode=None — the text is model-written prose, and a stray "<" both injects
        # markup and can make the send itself fail.
        await message.answer(answer, parse_mode=None)
    except Exception as exc:  # noqa: BLE001 — the client's message is already safe
        log.warning("ai_support.send_failed", user_id=user_id, error=str(exc))
        return False
    try:
        async with SessionFactory() as session:
            session.add(
                ConversationMessage(
                    user_id=user_id, direction="out", body=answer, via_ai=True
                )
            )
            await session.commit()
            if cfg.ping_ops:
                await ai_support.notify_ai_answered(session, cfg, who, question, answer)
    except Exception as exc:  # noqa: BLE001 — the client has their answer either way
        log.warning("ai_support.record_failed", user_id=user_id, error=str(exc))
    return True


@router.message(F.text & ~F.text.startswith("/"))
async def capture_message(message: Message) -> None:
    if message.from_user is None or not message.text:
        return
    body = message.text[:4096]
    async with SessionFactory() as session:
        user = await upsert_from_telegram(session, _identity(message))
        session.add(
            ConversationMessage(
                user_id=user.id,
                direction="in",
                body=body,
                tg_message_id=message.message_id,
            )
        )
        await session.commit()
        display = (
            f"@{user.tg_username}" if user.tg_username else (user.first_name or f"#{user.id}")
        )
        # The telegram id, not just the handle: a handle can be changed at any time and
        # the operator searching for this person afterwards needs the identifier that
        # cannot. Same reason the dossier keys off it.
        who = f"{display} (tg {user.tg_user_id})"
        user_id = user.id

        # The assistant gets first refusal on the message. It answers the handful of
        # simple product questions operators were retyping all day and hands back None for
        # everything else — money, access, stock, complaints — which falls through to the
        # operator path below exactly as before this existed.
        # Belt and braces: try_answer already swallows its own failures, and this catches
        # anything that gets past it — a bad settings row, a broken import. The assistant
        # is an optimisation on top of the operator path, and must never be able to take
        # that path down with it.
        ai_answer: str | None = None
        ai_cfg = ai_support.AiSupportConfig(enabled=False, ping_ops=False, ping_chat="")
        try:
            ai_cfg = await ai_support.get_config(session)
            if ai_cfg.enabled and not await _operator_active(session, user_id):
                ai_answer = await ai_support.try_answer(session, user, body)
        except Exception as exc:  # noqa: BLE001 — fall through to the operator
            log.warning("ai_support.layer_failed", user_id=user_id, error=str(exc))
            ai_answer = None

    # Answered: no operator fan-out and no acknowledgement — there is nothing for a human
    # to pick up, and "an operator will get back to you" after an answer reads as the
    # answer not counting. A send that fails returns False and escalates instead.
    if ai_answer is not None and await _deliver_ai_answer(
        message, user_id=user_id, who=who, question=body, answer=ai_answer, cfg=ai_cfg
    ):
        return

    async with SessionFactory() as session:
        ack_due = await _ack_is_due(session, user_id)

        # One alert per burst, not one per message: "hello", "are you there", "answer me"
        # is one person needing help, and three pings for it is how the ping that matters
        # gets ignored — a live test produced five in six minutes.
        if await _starts_a_burst(session, user_id):
            # Best-effort — never let a failed notify drop the stored message. Fans out to
            # every operator chat (support + the owner's channel); see ops_alerts.py.
            with contextlib.suppress(Exception):
                await ops_alerts.notify_ops(session, f"💬 New message from {who}:\n{body[:500]}")
        else:
            log.info("bot.alert_collapsed", user_id=user_id)

        # Resolved here, while a session is still open: the operator's edited wording
        # lives in app_settings, and what gets sent must be what gets recorded below.
        ack_text = await render(session, ACK_TEMPLATE, {}) if ack_due else None

    # Outside the session, and sent before it is recorded: a reply we failed to send must
    # not leave a row claiming we sent it. The reverse order costs a duplicate ack at
    # worst, and only if recording fails right after the send succeeded.
    if not ack_text:
        return
    try:
        await message.answer(ack_text)
    except Exception as exc:  # noqa: BLE001 — the client's message is already safe
        log.warning("bot.ack_send_failed", user_id=user_id, error=str(exc))
        return
    try:
        async with SessionFactory() as session:
            session.add(
                # No admin_id: nobody typed this. The dossier labels such a row as the
                # automatic reply it is, rather than crediting an operator with it.
                ConversationMessage(user_id=user_id, direction="out", body=ack_text)
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("bot.ack_record_failed", user_id=user_id, error=str(exc))

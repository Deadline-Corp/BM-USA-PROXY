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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionFactory
from app.core.logging import log
from app.models import ConversationMessage
from app.services import ops_alerts
from app.services.users import upsert_from_telegram

router = Router(name="conversation")

# What the client sees the moment their message lands. Until this existed, writing to the
# bot looked exactly like writing into a void: the message was stored and the operators
# were pinged, but nothing came back, so the only signal available to the person was
# silence — which reads as "nobody is there".
_ACK_TEXT = "Thank you for your message. Our operator will get back to you shortly."

# How long one acknowledgement covers. Somebody typing three lines in a row gets one
# reply, not three, and somebody already mid-conversation with a human is not told again
# that an operator will be in touch. Any outbound message resets it, the operator's own
# replies included — the promise has already been kept by then.
_ACK_COOLDOWN = timedelta(hours=1)


async def _ack_is_due(session: AsyncSession, user_id: int) -> bool:
    last_out = await session.scalar(
        select(func.max(ConversationMessage.created_at)).where(
            ConversationMessage.user_id == user_id,
            ConversationMessage.direction == "out",
        )
    )
    return last_out is None or datetime.now(UTC) - last_out >= _ACK_COOLDOWN


def _identity(message: Message) -> dict[str, Any]:
    u = message.from_user
    return {
        "tg_user_id": u.id if u else 0,
        "tg_username": u.username if u else None,
        "first_name": u.first_name if u else None,
        "last_name": u.last_name if u else None,
        "lang": (u.language_code if u else None) or "en",
    }


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

        # Best-effort operator alert — never let a failed notify drop the stored message.
        # Fans out to every operator chat (support + the owner's channel); see
        # services/ops_alerts.py for where the list comes from.
        with contextlib.suppress(Exception):
            await ops_alerts.notify_ops(session, f"💬 New message from {who}:\n{body[:500]}")

        user_id = user.id
        ack_due = await _ack_is_due(session, user_id)

    # Outside the session, and sent before it is recorded: a reply we failed to send must
    # not leave a row claiming we sent it. The reverse order costs a duplicate ack at
    # worst, and only if recording fails right after the send succeeded.
    if not ack_due:
        return
    try:
        await message.answer(_ACK_TEXT)
    except Exception as exc:  # noqa: BLE001 — the client's message is already safe
        log.warning("bot.ack_send_failed", user_id=user_id, error=str(exc))
        return
    try:
        async with SessionFactory() as session:
            session.add(
                # No admin_id: nobody typed this. The dossier labels such a row as the
                # automatic reply it is, rather than crediting an operator with it.
                ConversationMessage(user_id=user_id, direction="out", body=_ACK_TEXT)
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("bot.ack_record_failed", user_id=user_id, error=str(exc))

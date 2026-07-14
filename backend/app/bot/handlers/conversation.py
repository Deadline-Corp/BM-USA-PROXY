"""Catch-all inbound-message capture.

Stores any free-text DM a client sends the bot into the conversation thread so
operators can read + reply from the admin, and (best-effort) pings the operator
alert chat. Registered AFTER the command router so /start, /app, /help win first;
the ``~F.text.startswith("/")`` guard keeps stray slash-commands out of the thread.
"""

from __future__ import annotations

import contextlib
from typing import Any

from aiogram import F, Router
from aiogram.types import Message

from app.core.config import settings
from app.core.db import SessionFactory
from app.models import ConversationMessage
from app.services.users import upsert_from_telegram

router = Router(name="conversation")


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

    # Best-effort operator alert — never let a failed notify drop the stored message.
    if settings.ops_alert_chat_id and message.bot is not None:
        with contextlib.suppress(Exception):
            await message.bot.send_message(
                settings.ops_alert_chat_id,
                f"💬 New message from {display}:\n{body[:500]}",
            )

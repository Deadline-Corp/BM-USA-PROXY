"""Operator alerts — one place that knows who gets told when something needs a human.

There are several of these now (a client writing to the bot, a reseller enquiry, the pool
running low, the nightly reconciliation) and they all go to the same people. Without a
shared helper each caller grew its own copy of "read the chat id, get the bot, suppress
failures", and adding a second recipient would have meant editing every one of them.

Recipients come from two places, both allowed to be empty:
  * OPS_ALERT_CHAT_ID — deploy-time, comma-separated. Survives an empty database.
  * the `ops_alert_chats` app setting — editable in the admin console, so the client can
    add or remove a chat without a deploy.

**Use numeric ids for people.** An @username only works as a destination for a public
channel or supergroup. A private chat with a person can only be addressed by their numeric
Telegram id, and only after that person has pressed Start on the bot — Telegram does not
let a bot open a conversation. So an operator's @handle in this list silently resolves to
nothing, which is indistinguishable from "no alerts are firing".

Their id is on the Clients screen beside the handle, and in admin_users for anyone with a
console account.
"""

from __future__ import annotations

import contextlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import log
from app.services import settings as settings_svc

OPS_CHATS_SETTING = "ops_alert_chats"


def _split(raw: str | None) -> list[str]:
    return [part.strip() for part in (raw or "").replace(";", ",").split(",") if part.strip()]


async def ops_chat_ids(session: AsyncSession) -> list[str]:
    """Every chat that should hear about operator-facing events, de-duplicated."""
    configured = _split(settings.ops_alert_chat_id)
    stored = _split(str(await settings_svc.get(session, OPS_CHATS_SETTING, "") or ""))
    seen: dict[str, None] = {}
    for chat in (*configured, *stored):
        seen.setdefault(chat, None)
    return list(seen)


async def notify_ops(session: AsyncSession, text: str) -> int:
    """Send `text` to every operator chat. Returns how many accepted it.

    Best-effort by design: an alert is a courtesy on top of whatever was already stored,
    and a chat the bot was removed from must not turn a client's message into an error.
    Failures are logged rather than swallowed — a bot silently unable to reach any operator
    chat looks exactly like "nothing ever happens" from the outside.

    parse_mode=None throughout: alert bodies quote user-supplied text, and the bot defaults
    to HTML, where a stray tag both injects markup and can raise on send.
    """
    from app.bot.factory import get_bot

    bot = get_bot()
    if bot is None:
        return 0
    chats = await ops_chat_ids(session)
    if not chats:
        log.warning("ops_alert.no_recipients")
        return 0
    delivered = 0
    for chat in chats:
        try:
            await bot.send_message(chat, text, parse_mode=None)
            delivered += 1
        except Exception as exc:  # noqa: BLE001 — one bad chat must not block the others
            log.warning("ops_alert.failed", chat=chat, error=str(exc))
    return delivered


async def notify_ops_no_session(text: str) -> int:
    """Same, for callers that have no session of their own (bot handlers)."""
    from app.core.db import SessionFactory

    async with SessionFactory() as session:
        with contextlib.suppress(Exception):
            return await notify_ops(session, text)
    return 0

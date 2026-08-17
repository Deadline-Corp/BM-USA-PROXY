"""Operator alerts — one place that knows who gets told when something needs a human.

There are several of these now (a client writing to the bot, a reseller enquiry, the pool
running low, the nightly reconciliation) and they all go to the same people. Without a
shared helper each caller grew its own copy of "read the chat id, get the bot, suppress
failures", and adding a second recipient would have meant editing every one of them.

Recipients come from two places, both allowed to be empty:
  * OPS_ALERT_CHAT_ID — deploy-time, comma-separated. Survives an empty database.
  * the `ops_alert_chats` app setting — editable in the admin console, so the client can
    add or remove a chat without a deploy.

**Handles are welcome, and are resolved here.** Telegram itself only accepts an @username
for a public channel or supergroup — a private chat has to be addressed by numeric id, and
only after that person has pressed Start on the bot. But nobody remembers their colleague
as 6569763578, so an @handle written here is looked up against people who *have* started
the bot (console accounts first, then clients) and swapped for their id. A handle we cannot
resolve is passed through untouched: that is exactly the case where it names a channel,
which Telegram will deliver to.
"""

from __future__ import annotations

import contextlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import log
from app.models import AdminUser, User
from app.services import settings as settings_svc

OPS_CHATS_SETTING = "ops_alert_chats"


def _split(raw: str | None) -> list[str]:
    return [part.strip() for part in (raw or "").replace(";", ",").split(",") if part.strip()]


async def _resolve_handles(session: AsyncSession, chats: list[str]) -> list[str]:
    """Swap each @handle for the numeric id of the person behind it, where we know it.

    Console accounts are checked before clients: the same handle appearing in both is the
    same human, and the console row is the one an operator maintains deliberately.

    A handle nobody has started the bot from is left as-is rather than dropped — for a
    public channel that is the correct destination, and for a person it produces a logged
    delivery failure naming the handle, which is a far better clue than silence.
    """
    handles = {c.lstrip("@").lower() for c in chats if c.startswith("@")}
    if not handles:
        return chats

    resolved: dict[str, str] = {}
    pairs: list[tuple[str | None, int | None]] = []
    admin_rows = (
        await session.execute(
            select(AdminUser.telegram_username, AdminUser.telegram_user_id).where(
                func.lower(AdminUser.telegram_username).in_(handles),
                AdminUser.telegram_user_id.is_not(None),
            )
        )
    ).all()
    user_rows = (
        await session.execute(
            select(User.tg_username, User.tg_user_id).where(
                func.lower(User.tg_username).in_(handles)
            )
        )
    ).all()
    # Clients first, console accounts second: the later write wins, and a handle present
    # in both is the same human whose console row an operator maintains deliberately.
    pairs.extend((h, i) for h, i in user_rows)
    pairs.extend((h, i) for h, i in admin_rows)
    for handle, tg_id in pairs:
        if handle and tg_id:
            resolved[handle.lower()] = str(tg_id)

    out: list[str] = []
    for chat in chats:
        if chat.startswith("@"):
            found = resolved.get(chat.lstrip("@").lower())
            if found is None:
                log.info("ops_alert.handle_unresolved", handle=chat)
            out.append(found or chat)
        else:
            out.append(chat)
    return out


async def ops_chat_ids(session: AsyncSession) -> list[str]:
    """Every chat that should hear about operator-facing events, de-duplicated.

    De-duplicated *after* resolution, so the same person written once as @handle and once
    as an id does not get told twice.
    """
    configured = _split(settings.ops_alert_chat_id)
    stored = _split(str(await settings_svc.get(session, OPS_CHATS_SETTING, "") or ""))
    chats = await _resolve_handles(session, [*configured, *stored])
    seen: dict[str, None] = {}
    for chat in chats:
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

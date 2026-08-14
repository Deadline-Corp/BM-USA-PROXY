"""app_settings read/write helpers (referral params, invoice TTL, ToS, notify texts)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting


async def get(session: AsyncSession, key: str, default: Any = None) -> Any:
    row = await session.get(AppSetting, key)
    return row.value if row is not None else default


async def set_value(
    session: AsyncSession, key: str, value: Any, *, admin_id: int | None = None
) -> None:
    stmt = insert(AppSetting).values(key=key, value=value, updated_by=admin_id)
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={"value": stmt.excluded.value, "updated_by": admin_id},
    )
    await session.execute(stmt)


# ── Channel/Support links ────────────────────────────────────────────────
# Operator-editable in the admin Settings screen (bot_channel_url / bot_support_url — see
# api/admin/domain.py::_SETTINGS_WHITELIST). Read from here by every surface that shows
# these links — the bot keyboard (bot/handlers/start.py) and the mini-app's public
# GET /api/twa/links (api/twa/router.py) — so a link changed once in the admin updates
# everywhere at once. Living in two places is exactly how the client kept seeing "the
# button still goes back into the bot" after the first pass only touched the bot.
DEFAULT_CHANNEL_URL = "https://t.me/usproxyclub"
DEFAULT_SUPPORT_URL = "https://t.me/usproxy_support"


def tg_link(value: Any, default: str) -> str:
    """Normalize a settings value into a full t.me link: "@name" and "name" both become
    "https://t.me/name"; a value that already looks like a URL passes through unchanged
    (this is what lets an operator use a private invite link, e.g. "https://t.me/+AbCdEf",
    which has no @username to extract); blank/unset falls back to `default`.
    """
    text = str(value).strip() if value else ""
    if not text:
        return default
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return f"https://t.me/{text.lstrip('@')}"


async def app_links(session: AsyncSession) -> dict[str, str]:
    """Channel/support links, resolved from operator settings with defaults."""
    channel = await get(session, "bot_channel_url", "")
    support = await get(session, "bot_support_url", "")
    return {
        "channel_url": tg_link(channel, DEFAULT_CHANNEL_URL),
        "support_url": tg_link(support, DEFAULT_SUPPORT_URL),
    }

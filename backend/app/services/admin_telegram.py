"""Tying a console account to the Telegram account its login codes will be sent to.

A @handle is not an address. The Bot API has no call that turns a username into a chat for
a private individual, and a bot may not write to anyone who has not started it. So the
owner writes down the handle they know — the only identifier a person can actually tell you
over the phone — and the numeric id, the thing a message is addressed to, is bound when
that person opens the bot and presses Start.

Both sides are unique: two accounts must not claim one handle (the binding would be
ambiguous) and must not resolve to one inbox (a code minted for one would arrive for the
other).
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminUser

# Telegram's own rule is 5–32 of [A-Za-z0-9_] starting with a letter, but accounts made
# long ago carry shorter handles, so the low end is loosened rather than enforced against
# the person standing in front of you.
_HANDLE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


class InvalidHandle(ValueError):
    """The text does not look like a Telegram handle at all."""


def normalise_handle(raw: str | None) -> str | None:
    """`@Ivan_K `, `t.me/Ivan_K`, `Ivan_K` → `ivan_k`. Empty or blank → None (unset).

    Stored lowercase because Telegram treats handles case-insensitively while reporting
    them in whatever case the owner chose — matching on the raw string would miss.
    """
    if raw is None:
        return None
    handle = raw.strip()
    for prefix in ("https://", "http://", "t.me/", "telegram.me/", "@"):
        if handle.lower().startswith(prefix):
            handle = handle[len(prefix) :]
    handle = handle.strip()
    if not handle:
        return None
    if not _HANDLE_RE.match(handle):
        raise InvalidHandle(
            "not a Telegram handle — letters, digits and underscores, "
            "4 characters or more, e.g. @ivan_k"
        )
    return handle.lower()


async def handle_taken_by(
    session: AsyncSession, handle: str, *, excluding: int | None = None
) -> int | None:
    """The id of another account already holding this handle, if any."""
    stmt = select(AdminUser.id).where(func.lower(AdminUser.telegram_username) == handle)
    if excluding is not None:
        stmt = stmt.where(AdminUser.id != excluding)
    found: int | None = await session.scalar(stmt)
    return found


async def bind_from_start(session: AsyncSession, *, handle: str | None, tg_user_id: int) -> bool:
    """Someone pressed Start. If an account is waiting on their handle, bind it.

    Returns True when this call is what completed a binding, so the bot can say so.

    Deliberately narrow: only an account with no id yet is bound. A handle already pointing
    at an inbox is left alone — otherwise anyone who took over a freed-up username could
    redirect an operator's login codes to themselves. Re-binding is the owner's move: they
    clear the handle and write it again, and the console drops the old id with it.
    """
    if not handle:
        return False
    normalised = handle.lower()
    account = await session.scalar(
        select(AdminUser).where(
            func.lower(AdminUser.telegram_username) == normalised,
            AdminUser.telegram_user_id.is_(None),
            AdminUser.is_active.is_(True),
        )
    )
    if account is None:
        return False
    # The same person may hold two accounts on paper; the id is unique in the database, so
    # refuse here rather than crash on the constraint.
    clash = await session.scalar(
        select(AdminUser.id).where(AdminUser.telegram_user_id == tg_user_id)
    )
    if clash is not None:
        return False
    account.telegram_user_id = tg_user_id
    return True

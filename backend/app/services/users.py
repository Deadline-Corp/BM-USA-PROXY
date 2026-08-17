"""User upsert (from Telegram identity) and the Terms-of-Use gate."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, ValidationError
from app.core.logging import log
from app.models import TosAcceptance, User
from app.services import settings as settings_svc

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _gen_referral_code() -> str:
    return secrets.token_hex(4).upper()  # 8 hex chars


async def upsert_from_telegram(session: AsyncSession, identity: dict[str, Any]) -> User:
    now = datetime.now(UTC)
    user = await session.scalar(
        select(User).where(User.tg_user_id == identity["tg_user_id"])
    )
    if user is not None:
        user.tg_username = identity.get("tg_username")
        user.first_name = identity.get("first_name")
        user.last_name = identity.get("last_name")
        user.last_seen_at = now
        return user

    for _ in range(5):  # retry on the (astronomically rare) referral_code collision
        code = _gen_referral_code()
        if not await session.scalar(select(User.id).where(User.referral_code == code)):
            break
    user = User(
        tg_user_id=identity["tg_user_id"],
        tg_username=identity.get("tg_username"),
        first_name=identity.get("first_name"),
        last_name=identity.get("last_name"),
        lang=identity.get("lang", "en"),
        referral_code=code,
        last_seen_at=now,
    )
    session.add(user)
    await session.flush()
    return user


# ── Terms of Use ────────────────────────────────────────────────────────
async def get_terms(session: AsyncSession) -> dict[str, Any]:
    tos = await settings_svc.get(session, "tos", {})
    return {
        "version": tos.get("version"),
        "text_md": tos.get("text_md", ""),
        "questions": tos.get("questions", []),
    }


async def is_tos_accepted(session: AsyncSession, user: User) -> bool:
    tos = await settings_svc.get(session, "tos", {})
    version = tos.get("version")
    if not version:
        return True
    return bool(
        await session.scalar(
            select(TosAcceptance.id).where(
                TosAcceptance.user_id == user.id, TosAcceptance.version == version
            )
        )
    )


def _validate_answers(questions: list[dict], answers: dict[str, Any]) -> None:
    for q in questions:
        qid, required, qtype = q["id"], q.get("required", False), q.get("type", "text")
        val = (answers or {}).get(qid)
        if required and not val:
            raise ValidationError(f"'{q.get('label', qid)}' is required")
        if val and qtype == "email" and not _EMAIL_RE.match(str(val)):
            raise ValidationError("invalid email")


async def accept_terms(
    session: AsyncSession, user: User, *, version: int, answers: dict[str, Any], source: str
) -> None:
    tos = await settings_svc.get(session, "tos", {})
    current = tos.get("version")
    if version != current:
        raise Conflict(f"terms version outdated; current is {current}")
    _validate_answers(tos.get("questions", []), answers)
    stmt = insert(TosAcceptance).values(
        user_id=user.id, version=version, source=source, answers=answers or {}
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "version"])
    await session.execute(stmt)
    email = (answers or {}).get("email")
    if email:
        user.email = email


async def refresh_handles(
    session: AsyncSession, bot: Any, *, batch: int = 300, active_days: int = 90
) -> dict[str, int]:
    """Re-read handles from Telegram for the clients checked longest ago.

    Telegram never announces a rename, and the data it attaches to a bot message or a
    mini-app request is cached by the client: measured 2026-08-17, somebody who had renamed
    themselves hours earlier still arrived as their old handle, while getChat answered with
    the new one straight away. So a visit alone is not enough to keep the console honest —
    support searches for the handle a customer just quoted and finds nobody.

    Walks in batches, oldest check first (never-checked first), so the cost per pass is
    fixed whatever the size of the client list and the whole list still comes round.
    Restricted to clients seen in the last `active_days`: somebody who has not opened the
    app in a year does not need their handle polled forever.

    One failure does not stop the walk — a person who blocked the bot or deleted their
    account answers with an error, and that is a fact about them, not a fault here. They
    are still stamped as checked so the walk moves on rather than retrying them every pass.
    """
    cutoff = datetime.now(UTC) - timedelta(days=active_days)
    rows = (
        await session.execute(
            select(User)
            .where(User.last_seen_at.is_not(None), User.last_seen_at >= cutoff)
            .order_by(User.handle_checked_at.asc().nullsfirst())
            .limit(batch)
        )
    ).scalars().all()

    now = datetime.now(UTC)
    checked = changed = failed = 0
    for user in rows:
        try:
            chat = await bot.get_chat(user.tg_user_id)
        except Exception as exc:  # noqa: BLE001 — blocked/deleted accounts are expected
            user.handle_checked_at = now
            failed += 1
            log.info("handles.refresh_failed", tg_user_id=user.tg_user_id, error=str(exc))
            continue
        checked += 1
        user.handle_checked_at = now
        if chat.username != user.tg_username:
            log.info(
                "handles.renamed",
                tg_user_id=user.tg_user_id,
                was=user.tg_username,
                now=chat.username,
            )
            user.tg_username = chat.username
            changed += 1
        # Names move too, and the console shows them beside the handle.
        if chat.first_name:
            user.first_name = chat.first_name
        if chat.last_name:
            user.last_name = chat.last_name

    log.info("handles.refresh", checked=checked, changed=changed, failed=failed)
    return {"checked": checked, "changed": changed, "failed": failed}

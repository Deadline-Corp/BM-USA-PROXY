"""User upsert (from Telegram identity) and the Terms-of-Use gate."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, ValidationError
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

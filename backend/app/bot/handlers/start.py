"""/start, /app, /help — onboarding, deep-link capture (referral + post attribution),
open-the-app button, and the Terms-of-Use prompt.
"""

from __future__ import annotations

from typing import Any

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from app.core.config import settings
from app.core.db import SessionFactory
from app.services import admin_telegram, content, referral
from app.services.users import is_tos_accepted, upsert_from_telegram

router = Router(name="start")


def _open_app_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Open BM USA Proxy",
                    web_app=WebAppInfo(url=f"{settings.public_base_url}/app"),
                )
            ],
            [
                InlineKeyboardButton(text="Channel", url="https://t.me/usproxyclub"),
                InlineKeyboardButton(text="Support", url="https://t.me/usproxy_support"),
            ],
        ]
    )


# The mini-app hands out `?start=ref_<code>` (frontend/miniapp ReferralScreen.tsx) while
# this handler was written to the spec's shorter `r_`. Nothing ever errored: the payload
# simply failed to match, so /start fell through, no referrer was bound, and the referral
# ledger stayed empty for every user since launch. Both spellings are accepted now — a
# deep link, once shared, lives in someone's chat history forever, so the ones already out
# there have to keep working whichever prefix they carry. Longest prefix first.
_REFERRAL_PREFIXES = ("ref_", "r_")
_POST_PREFIX = "p_"


def referral_code_from(payload: str | None) -> str | None:
    """The referral code behind a /start payload, whichever accepted prefix it carries."""
    if not payload:
        return None
    for prefix in _REFERRAL_PREFIXES:
        if payload.startswith(prefix):
            return payload[len(prefix) :] or None
    return None


def _identity(message: Message) -> dict[str, Any]:
    u = message.from_user
    return {
        "tg_user_id": u.id if u else 0,
        "tg_username": u.username if u else None,
        "first_name": u.first_name if u else None,
        "last_name": u.last_name if u else None,
        "lang": (u.language_code if u else None) or "en",
    }


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    payload = command.args
    async with SessionFactory() as session:
        user = await upsert_from_telegram(session, _identity(message))
        code = referral_code_from(payload)
        if code:
            await referral.try_bind(session, referee=user, code=code)
        elif payload and payload.startswith(_POST_PREFIX):
            await content.record_click(
                session, code=payload[len(_POST_PREFIX) :], user=user
            )
        accepted = await is_tos_accepted(session, user)
        # If the console is waiting on this handle, this is the moment it gets an address
        # to send login codes to. Silent for everyone else — the overwhelming majority of
        # people pressing Start are customers, not operators.
        linked = await admin_telegram.bind_from_start(
            session,
            handle=(message.from_user.username if message.from_user else None),
            tg_user_id=user.tg_user_id,
        )
        await session.commit()

    if linked:
        await message.answer(
            "Your admin console account is now linked to this chat — "
            "sign-in codes will arrive here."
        )

    await message.answer(
        "Welcome to <b>BM USA Proxy</b> — premium USA mobile proxies.\n\n"
        "Tap below to open the app and get started.",
        reply_markup=_open_app_keyboard(),
    )
    if not accepted:
        await message.answer(
            "Please read and accept our Terms of Use first, then we'll provide you "
            "with a proxy.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text="Read & accept Terms",
                        web_app=WebAppInfo(url=f"{settings.public_base_url}/app?screen=terms"),
                    )
                ]]
            ),
        )


@router.message(Command("app"))
async def cmd_app(message: Message) -> None:
    await message.answer("Open the app:", reply_markup=_open_app_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Need help? Contact @usproxy_support.\n"
        "All actions (buy, my access, referrals) are inside the app.",
        reply_markup=_open_app_keyboard(),
    )

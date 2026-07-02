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
from app.services import content, referral
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
        if payload and payload.startswith("r_"):
            await referral.try_bind(session, referee=user, code=payload[2:])
        elif payload and payload.startswith("p_"):
            await content.record_click(session, code=payload[2:], user=user)
        accepted = await is_tos_accepted(session, user)
        await session.commit()

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

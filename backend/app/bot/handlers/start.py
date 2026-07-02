"""/start, /app, /help — onboarding + open-the-app button.

Deep-link payload handling (referral `r_…`, post attribution `p_…`) and the Terms
gate message are wired to service stubs now and completed in Stage 3/4 (BOT-4.1).
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from app.core.config import settings

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


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    # payload = command.args  → r_<code> (referral) | p_<code> (post attribution)
    # Stage 4 (BOT-4.1): upsert user, record_click / try_bind here.
    await message.answer(
        "Welcome to <b>BM USA Proxy</b> — premium USA mobile proxies.\n\n"
        "Tap below to open the app and get started.",
        reply_markup=_open_app_keyboard(),
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

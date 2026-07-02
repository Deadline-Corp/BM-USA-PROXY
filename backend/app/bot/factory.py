"""aiogram Bot + Dispatcher factory. Bot is reused by the worker for notifications.

The bot is intentionally minimal (client's decision): onboarding, Terms gate, deep-link
capture, and notification delivery — no purchases. Full handlers land in Stage 3/4.
"""

from __future__ import annotations

from functools import lru_cache

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from app.core.config import settings
from app.core.redis import redis_client


@lru_cache
def get_bot() -> Bot | None:
    if not settings.bot_token:
        return None
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


@lru_cache
def get_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=RedisStorage(redis=redis_client))
    from app.bot.handlers import start

    dp.include_router(start.router)
    return dp

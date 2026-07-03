"""Render + deliver queued notifications to users via the bot (worker `send_outbox`)."""

from __future__ import annotations

import re
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import User
from app.services import settings as settings_svc
from app.services.notifications import pending_batch

DEFAULT_TEXTS: dict[str, str] = {
    "welcome": "Welcome to <b>BM USA Proxy</b>! Tap below to open the app.",
    "payment_received": "Payment received — issuing your proxy now.",
    "access_issued": "Your proxy is ready! Open the app to view your access.",
    "provisioning_delayed": "We're preparing your proxy — it'll be ready shortly.",
    "access_expiring_24h": "Your proxy expires in 24 hours. Extend it in the app.",
    "access_expiring_1h": "Your proxy expires in 1 hour. Extend it now to stay connected.",
    "access_expired": "Your proxy has expired. Grab a new one in the app.",
    "access_extended": "Your proxy was extended — enjoy!",
    "access_reissued": "Your proxy was reissued — open the app for the new credentials.",
    "refund_processed": "Your refund has been processed.",
    "referral_joined": "A new user joined with your referral link!",
    "referral_accrued": "You earned ${amount_usd} from a referral (on hold).",
    "referral_available": "${amount_usd} of referral earnings is now available.",
    "payout_paid": "Your payout of ${amount_usd} was sent. Tx: {tx_hash}",
    "payout_rejected": "Your payout request was rejected: {reason}",
    "config_delivered": "Your config is on the way.",
    "operator_message": "{text}",
}

_APP_BUTTON_CODES = {
    "access_issued", "access_expiring_24h", "access_expiring_1h",
    "access_expired", "access_extended", "access_reissued",
}


_PLACEHOLDER = re.compile(r"\{(\w+)\}")


async def render(session: AsyncSession, code: str, payload: dict[str, Any]) -> str | None:
    override = await settings_svc.get(session, f"notify_texts:{code}", None)
    template = override if isinstance(override, str) and override else DEFAULT_TEXTS.get(code)
    if not template:
        return None
    data = payload or {}
    # Plain {name} substitution — NOT str.format, which would let an operator-editable
    # template do {x.__class__...} attribute traversal. \w+ never matches a dotted path.
    return _PLACEHOLDER.sub(lambda m: str(data.get(m.group(1), "")), template)


def _keyboard(code: str) -> InlineKeyboardMarkup | None:
    if code in _APP_BUTTON_CODES:
        url = f"{settings.public_base_url}/app"
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Open app", web_app=WebAppInfo(url=url))]]
        )
    return None


async def deliver_pending(session: AsyncSession, bot: Bot, *, limit: int = 25) -> dict[str, int]:
    batch = await pending_batch(session, limit)
    sent = failed = blocked = 0
    for n in batch:
        user = await session.get(User, n.user_id)
        text = await render(session, n.template_code, n.payload)
        if user is None or text is None:
            n.status = "skipped"
            continue
        try:
            await bot.send_message(user.tg_user_id, text, reply_markup=_keyboard(n.template_code))
            n.status = "sent"
            sent += 1
        except TelegramForbiddenError:
            n.status = "blocked"
            user.is_bot_blocked = True
            blocked += 1
        except TelegramRetryAfter:
            n.attempts += 1  # leave pending; next tick retries
        except Exception as exc:  # noqa: BLE001
            n.attempts += 1
            n.last_error = str(exc)[:300]
            if n.attempts >= 5:
                n.status = "failed"
                failed += 1
    return {"sent": sent, "failed": failed, "blocked": blocked}

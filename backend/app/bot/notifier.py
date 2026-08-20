"""Render + deliver queued notifications to users via the bot (worker `send_outbox`)."""

from __future__ import annotations

import re
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import User
from app.services import settings as settings_svc
from app.services.notifications import pending_batch

DEFAULT_TEXTS: dict[str, str] = {
    "welcome": "Welcome to <b>BM USA Proxy</b>! Tap below to open the app.",
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
    "config_delivered": "Here is your {config_type} config. Import the file into your VPN app.",
    "operator_message": "{text}",
    # What the bot says when it has nothing else to say — a message it did not answer
    # itself is on its way to a human. Delivered inline by the bot handler, not through
    # the outbox, but the text lives here so operators can edit it like any other.
    "bot_auto_reply": "Thank you for your message. Our operator will get back to you shortly.",
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
            if n.template_code == "config_delivered":
                await _send_config(session, bot, user, n.payload or {}, caption=text)
            else:
                await bot.send_message(
                    user.tg_user_id, text, reply_markup=_keyboard(n.template_code)
                )
            n.status = "sent"
            sent += 1
        except TelegramForbiddenError:
            n.status = "blocked"
            user.is_bot_blocked = True
            blocked += 1
        except TelegramRetryAfter:
            n.attempts += 1  # leave pending; next tick retries
            if n.attempts >= 10:
                n.status = "failed"
                failed += 1
        except Exception as exc:  # noqa: BLE001
            n.attempts += 1
            n.last_error = str(exc)[:300]
            if n.attempts >= 5:
                n.status = "failed"
                failed += 1
    return {"sent": sent, "failed": failed, "blocked": blocked}


async def _send_config(
    session: AsyncSession, bot: Bot, user: User, payload: dict[str, Any], *, caption: str
) -> None:
    """Fetch a VPN config and send it as a file.

    A document, not a message. WireGuard and OpenVPN clients import a file; a config
    pasted into a chat comes back with the line breaks mangled and the newcomer's first
    experience of the product is an import error they cannot diagnose.

    The config is fetched here rather than carried in the notification payload, for two
    reasons: it contains a private key, and a key we never write into our database cannot
    leak from it; and this runs inside the outbox, so a provider hiccup is a retry instead
    of a lost purchase.
    """
    from app.models import Access
    from app.services import vpn_configs

    kind = str(payload.get("config_type") or "")
    public_id = str(payload.get("access_public_id") or "")
    access = await session.scalar(select(Access).where(Access.public_id == public_id))
    if access is None or access.user_id != user.id:
        raise ValueError(f"config requested for an access that is not this user's: {public_id}")

    data = await vpn_configs.ensure_config(session, access, kind)
    await bot.send_document(
        user.tg_user_id,
        BufferedInputFile(data, filename=vpn_configs.filename_for(access, kind)),
        caption=caption,
    )

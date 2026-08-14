"""/start, /app, /help — onboarding, deep-link capture (referral + post attribution),
and the open-the-app button.
"""

from __future__ import annotations

from typing import Any

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionFactory
from app.core.logging import log
from app.services import admin_telegram, content, media, referral
from app.services import settings as settings_svc
from app.services.users import upsert_from_telegram

router = Router(name="start")


async def _app_links(session: AsyncSession) -> tuple[str, str]:
    """Channel/support links, operator-editable in the admin Settings screen.

    Resolved via the shared app.services.settings.app_links() helper so the bot keyboard
    and the mini-app's GET /api/twa/links endpoint read the exact same values and defaults
    — see settings.py for the normalization rules and DEFAULT_CHANNEL_URL/DEFAULT_SUPPORT_URL.
    """
    links = await settings_svc.app_links(session)
    return links["channel_url"], links["support_url"]


def _open_app_keyboard(channel_url: str, support_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Get proxy",
                    web_app=WebAppInfo(url=f"{settings.public_base_url}/app"),
                )
            ],
            [
                InlineKeyboardButton(text="Channel", url=channel_url),
                InlineKeyboardButton(text="Support", url=support_url),
            ],
        ]
    )


# Caption text lives here, not just inline in cmd_start, so _send_welcome_photo can check
# its length against Telegram's own limit before deciding whether the buttons ride with the
# photo or with a separate text message.
_WELCOME_TEXT = (
    "Welcome to <b>BM USA Proxy</b> — premium USA mobile proxies.\n\n"
    "Tap below to open the app and get started."
)
_CAPTION_LIMIT = 1024  # Telegram's hard cap on a photo message's caption.


async def _send_welcome_photo(
    message: Message, keyboard: InlineKeyboardMarkup, *, cached_file_id: str | None
) -> None:
    """The /start greeting: the coverage-map photo, captioned with the welcome text and
    carrying the Get proxy / Channel / Support buttons — falling all the way back to a
    text-only message (the previous greeting) if anything about the picture goes wrong.
    The greeting has to reach the user; the photo is a nice-to-have riding on top of it.

    Sent by the cached Telegram `file_id` (app_settings key
    media.WELCOME_IMAGE_FILE_ID_SETTING) whenever one exists — free for Telegram to resend,
    no bytes re-uploaded, which matters once this goes out on every /start rather than once.
    media.set_welcome_image() deletes that setting the instant an operator replaces the
    image (api/admin/domain.py), so a stale id can only be read here in the narrow window
    before this function re-caches the new one below — it can never be served forever.
    """
    fits_caption = len(_WELCOME_TEXT) <= _CAPTION_LIMIT
    caption = _WELCOME_TEXT if fits_caption else None
    photo_markup = keyboard if fits_caption else None

    async def _send_text_if_uncaptioned() -> None:
        if not fits_caption:
            await message.answer(_WELCOME_TEXT, reply_markup=keyboard)

    if cached_file_id:
        try:
            await message.answer_photo(
                cached_file_id, caption=caption, reply_markup=photo_markup
            )
        except Exception as exc:  # noqa: BLE001 — any failure falls through to a re-upload
            # Expected when Telegram invalidates the id; the bytes are re-sent below, so
            # this is recoverable. Logged rather than swallowed: if it starts happening on
            # every /start, the cache is broken and nothing else would say so.
            log.warning("bot.welcome_photo_cached_failed", error=str(exc))
        else:
            await _send_text_if_uncaptioned()
            return

    try:
        async with SessionFactory() as session:
            asset = await media.get_welcome_image(session)
            sent = await message.answer_photo(
                BufferedInputFile(asset.data, filename="welcome.jpg"),
                caption=caption,
                reply_markup=photo_markup,
            )
            new_file_id = sent.photo[-1].file_id if sent.photo else None
            if new_file_id:
                await settings_svc.set_value(
                    session, media.WELCOME_IMAGE_FILE_ID_SETTING, new_file_id
                )
            await session.commit()
    except Exception:
        # The photo failed outright (network blip, Telegram hiccup, whatever) — the
        # greeting itself still has to arrive.
        await message.answer(_WELCOME_TEXT, reply_markup=keyboard)
        return

    await _send_text_if_uncaptioned()


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
            # The click is counted first and separately: try_bind refuses a visitor who
            # already has a referrer, and refusing to bind them is not a reason to pretend
            # they never arrived.
            await referral.record_click(session, code=code, visitor=user)
            await referral.try_bind(session, referee=user, code=code)
        elif payload and payload.startswith(_POST_PREFIX):
            await content.record_click(
                session, code=payload[len(_POST_PREFIX) :], user=user
            )
        channel_url, support_url = await _app_links(session)
        cached_file_id = await settings_svc.get(session, media.WELCOME_IMAGE_FILE_ID_SETTING)
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

    await _send_welcome_photo(
        message, _open_app_keyboard(channel_url, support_url), cached_file_id=cached_file_id
    )


@router.message(Command("app"))
async def cmd_app(message: Message) -> None:
    async with SessionFactory() as session:
        channel_url, support_url = await _app_links(session)
    await message.answer(
        "Open the app:", reply_markup=_open_app_keyboard(channel_url, support_url)
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    async with SessionFactory() as session:
        channel_url, support_url = await _app_links(session)
    await message.answer(
        "Need help? Use the Support button below.\n"
        "All actions (buy, my access, referrals) are inside the app.",
        reply_markup=_open_app_keyboard(channel_url, support_url),
    )

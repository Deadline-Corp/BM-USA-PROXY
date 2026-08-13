"""The one-time code that stands between a correct password and the console.

A password alone is one secret, and secrets travel: written down, reused, typed on somebody
else's laptop. This adds a second one that cannot be written down in advance — six digits,
good for five minutes, delivered to the Telegram account the owner bound to that console
account. Getting in means holding both the password and that phone.

The code lives in Redis, never in the database: it is worthless after five minutes and
there is no reason to keep a record of it. What is kept is the ticket — a random string
handed to the browser between the two steps, which is only good for submitting a code. It
cannot open the console on its own, so a password that stops at step one gets nowhere.
"""

from __future__ import annotations

import hashlib
import secrets

from app.core.redis import redis_client

CODE_TTL_SECONDS = 300
MAX_ATTEMPTS = 5
_PREFIX = "admin_login_otp:"


class DeliveryFailed(Exception):
    """The code could not be delivered, so there is nothing for the person to type."""


def _key(ticket: str) -> str:
    return f"{_PREFIX}{ticket}"


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


async def issue(admin_id: int) -> tuple[str, str]:
    """Mint a ticket and its code. Returns (ticket, code) — the code is sent, never stored.

    Only the digest is kept, which costs nothing and means a dump of Redis does not hand
    somebody a live code for every session in flight.
    """
    ticket = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1_000_000):06d}"
    key = _key(ticket)
    await redis_client.hset(key, mapping={"admin_id": admin_id, "code": _digest(code)})  # type: ignore[misc]
    await redis_client.expire(key, CODE_TTL_SECONDS)
    return ticket, code


async def verify(ticket: str, code: str) -> int | None:
    """Return the admin id if the code is right, else None. Single use either way it ends.

    Wrong guesses are counted and the ticket dies on the fifth, which is what keeps six
    digits meaningful: a million possibilities are only worth anything if you cannot try
    them. `HINCRBY` does the counting so two requests at once cannot both see "attempt 1".
    """
    key = _key(ticket)
    # Read and count in one transaction. Apart they race with the five-minute expiry: the
    # ticket can lapse between the two calls, and then the increment quietly recreates it —
    # as a hash holding nothing but a counter, with no expiry, for good.
    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.hgetall(key)
        pipe.hincrby(key, "attempts", 1)
        stored, attempts = await pipe.execute()
    if not stored:
        # Expired or already spent. The increment above just built that empty shell —
        # take it back out.
        await redis_client.delete(key)
        return None
    if attempts > MAX_ATTEMPTS:
        await redis_client.delete(key)
        return None
    expected = stored.get("code")
    if not expected or not secrets.compare_digest(expected, _digest(code.strip())):
        return None
    await redis_client.delete(key)
    return int(stored["admin_id"])


async def deliver(chat_id: int, code: str) -> None:
    """Send the code to the bound chat, or say plainly that it could not be sent.

    A failure here must stop the login. Letting somebody through because the message did
    not go out would turn the second factor off for exactly the people it should stop.
    """
    from aiogram.exceptions import TelegramAPIError

    from app.bot.factory import get_bot

    bot = get_bot()
    if bot is None:
        raise DeliveryFailed("bot is not configured")
    try:
        await bot.send_message(
            chat_id,
            f"Sign-in code: <b>{code}</b>\n\n"
            "It expires in 5 minutes and works once.\n"
            "If you are not signing in to the admin console right now, ignore this "
            "message and change your password.",
        )
    except TelegramAPIError as exc:
        raise DeliveryFailed(str(exc)) from exc

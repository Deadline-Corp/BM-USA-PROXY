"""Security primitives: admin passwords (argon2), admin JWT, credential encryption
(Fernet), and Telegram Mini-App initData validation.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet

from app.core.config import settings
from app.core.errors import Unauthorized, ValidationError

# ── Admin passwords ─────────────────────────────────────────────────────
_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


# ── Admin JWT ───────────────────────────────────────────────────────────
_JWT_ISS = "bm-usa-proxy"
_JWT_AUD = "admin-api"


def _now() -> datetime:
    return datetime.now(tz=UTC)


def create_access_token(admin_id: int, role: str) -> str:
    payload = {
        "sub": str(admin_id),
        "role": role,
        "type": "access",
        "jti": uuid.uuid4().hex,
        "iss": _JWT_ISS,
        "aud": _JWT_AUD,
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(minutes=settings.admin_jwt_ttl_min)).timestamp()),
    }
    return jwt.encode(payload, settings.admin_jwt_secret, algorithm="HS256")


def create_refresh_token(admin_id: int) -> str:
    payload = {
        "sub": str(admin_id),
        "type": "refresh",
        "jti": uuid.uuid4().hex,
        "iss": _JWT_ISS,
        "aud": _JWT_AUD,
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(days=settings.admin_refresh_ttl_days)).timestamp()),
    }
    return jwt.encode(payload, settings.admin_jwt_secret, algorithm="HS256")


def decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.admin_jwt_secret,
            algorithms=["HS256"],
            issuer=_JWT_ISS,
            audience=_JWT_AUD,
        )
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthorized("invalid token") from exc
    if payload.get("type") != expected_type:
        raise Unauthorized("wrong token type")
    return payload


# ── JWT blacklist (logout / revocation) via Redis ───────────────────────
def _bl_key(jti: str) -> str:
    return f"jwt:bl:{jti}"


async def blacklist_token(jti: str, exp: int) -> None:
    """Mark a token's jti as revoked until its `exp` (unix seconds)."""
    from app.core.redis import redis_client

    ttl = max(1, exp - int(_now().timestamp()))
    await redis_client.set(_bl_key(jti), "1", ex=ttl)


async def is_blacklisted(jti: str) -> bool:
    from app.core.redis import redis_client

    return bool(await redis_client.get(_bl_key(jti)))


# ── Credential encryption (proxy host:port:login:pass at rest) ──────────
def _fernet() -> Fernet:
    if not settings.credentials_key:
        raise RuntimeError("CREDENTIALS_KEY is not set")
    return Fernet(settings.credentials_key.encode())


def encrypt_credentials(data: dict[str, Any]) -> bytes:
    return _fernet().encrypt(json.dumps(data, separators=(",", ":")).encode())


def decrypt_credentials(token: bytes) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(_fernet().decrypt(token).decode())
    return result


# ── Telegram Mini-App initData ──────────────────────────────────────────
INIT_DATA_MAX_AGE_SECONDS = 24 * 3600


def parse_init_data(init_data_raw: str) -> dict[str, Any]:
    """Validate Telegram WebApp initData HMAC and freshness; return the user dict.

    Raises ValidationError on a bad signature, missing user, or stale auth_date.
    """
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is not set")

    # aiogram implements the exact HMAC scheme from Telegram's spec.
    from aiogram.utils.web_app import safe_parse_webapp_init_data

    try:
        parsed = safe_parse_webapp_init_data(settings.bot_token, init_data_raw)
    except Exception as exc:  # aiogram raises ValueError on bad hash
        raise ValidationError("invalid initData signature") from exc

    auth_date = int(parsed.auth_date.timestamp()) if parsed.auth_date else 0
    if not auth_date or (time.time() - auth_date) > INIT_DATA_MAX_AGE_SECONDS:
        raise ValidationError("initData is stale")

    if parsed.user is None:
        raise ValidationError("initData has no user")

    return {
        "tg_user_id": parsed.user.id,
        "tg_username": parsed.user.username,
        "first_name": parsed.user.first_name,
        "last_name": parsed.user.last_name,
        "lang": parsed.user.language_code or "en",
        "start_param": parsed.start_param,
    }

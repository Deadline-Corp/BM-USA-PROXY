"""Pure-unit tests for security primitives (no DB needed)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse

import pytest
from app.core.config import settings
from app.core.errors import Unauthorized, ValidationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    decrypt_credentials,
    encrypt_credentials,
    hash_password,
    parse_init_data,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    h = hash_password("s3cret-pw")
    assert h != "s3cret-pw"
    assert verify_password("s3cret-pw", h)
    assert not verify_password("wrong", h)


def test_access_token_roundtrip() -> None:
    token = create_access_token(admin_id=7, role="owner")
    claims = decode_token(token, expected_type="access")
    assert claims["sub"] == "7"
    assert claims["role"] == "owner"


def test_wrong_token_type_rejected() -> None:
    refresh = create_refresh_token(admin_id=1)
    with pytest.raises(Unauthorized):
        decode_token(refresh, expected_type="access")


def test_tampered_token_rejected() -> None:
    token = create_access_token(admin_id=1, role="operator")
    with pytest.raises(Unauthorized):
        decode_token(token + "x", expected_type="access")


def test_credentials_encryption_roundtrip() -> None:
    data = {"host": "1.2.3.4", "http_port": 8080, "login": "u", "password": "p"}
    blob = encrypt_credentials(data)
    assert blob != json.dumps(data).encode()
    assert decrypt_credentials(blob) == data


# --- Telegram initData -----------------------------------------------------
def _build_init_data(token: str, user: dict, auth_date: int | None = None) -> str:
    auth_date = auth_date or int(time.time())
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAA",
        "user": json.dumps(user, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    return urllib.parse.urlencode(fields)


def test_init_data_valid() -> None:
    user = {"id": 555, "username": "neo", "first_name": "Thomas", "language_code": "en"}
    raw = _build_init_data(settings.bot_token, user)
    identity = parse_init_data(raw)
    assert identity["tg_user_id"] == 555
    assert identity["tg_username"] == "neo"


def test_init_data_bad_signature() -> None:
    user = {"id": 1, "first_name": "X"}
    raw = _build_init_data("999999:WRONG-TOKEN", user)
    with pytest.raises(ValidationError):
        parse_init_data(raw)


def test_init_data_stale() -> None:
    user = {"id": 1, "first_name": "X"}
    raw = _build_init_data(settings.bot_token, user, auth_date=int(time.time()) - 90000)
    with pytest.raises(ValidationError):
        parse_init_data(raw)

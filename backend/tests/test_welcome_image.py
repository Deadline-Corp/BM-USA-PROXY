"""Welcome-image admin upload, and the file_id cache it has to keep honest.

Two things are load-bearing here and both get their own coverage:
  - the upload endpoint validates by the file's own magic bytes, not the client's claimed
    Content-Type, and enforces a size cap — see app/services/media.py::sniff_image_content_type
  - replacing the image clears the cached Telegram file_id (app_settings key
    'welcome_image_file_id'), because bot/handlers/start.py resends by that id and a stale
    one would keep the old photo going out on every /start forever.

Endpoint tests go through the real FastAPI route + real Postgres session, matching
test_locations.py's shape. The _send_welcome_photo tests at the bottom mock only the
Telegram boundary (Message.answer / .answer_photo) — everything else, including the DB
session, is real. SessionFactory is monkeypatched to the isolated test database because
that helper opens its own session rather than taking one as a parameter (aiogram handlers
have no per-request DI hook the way FastAPI routes do via dependency_overrides).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest_asyncio
from app.api import deps
from app.core.config import settings
from app.core.redis import redis_client
from app.main import app
from app.models import AppSetting
from app.services import media
from app.services import settings as settings_svc
from httpx import ASGITransport, AsyncClient
from scripts.seed import seed_admin, seed_settings
from sqlalchemy.ext.asyncio import async_sessionmaker

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _fake_jpeg(size: int = 256) -> bytes:
    return _JPEG_MAGIC + b"\x00" * (size - len(_JPEG_MAGIC))


@pytest_asyncio.fixture
async def ctx(engine):
    await redis_client.flushdb()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await seed_settings(s)
        await seed_admin(s)
        await s.commit()

    async def _db():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[deps.db_session] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        pwd = settings.seed_admin_password
        assert pwd is not None
        r = await c.post(
            "/api/admin/auth/login",
            json={"email": settings.seed_admin_email, "password": pwd.get_secret_value()},
        )
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield c, maker
    app.dependency_overrides.clear()


# ── upload endpoint: validation + storage ───────────────────────────────────


async def test_upload_valid_image_replaces_default(ctx) -> None:
    client, _maker = ctx
    data = _fake_jpeg()

    r = await client.post(
        "/api/admin/settings/welcome-image",
        files={"file": ("coverage.jpg", data, "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["content_type"] == "image/jpeg"
    assert body["size_bytes"] == len(data)

    got = await client.get("/api/admin/settings/welcome-image")
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("image/jpeg")
    assert got.content == data

    # Same baseline RBAC check every admin endpoint gets in this suite.
    del client.headers["Authorization"]
    assert (await client.get("/api/admin/settings/welcome-image")).status_code == 401


async def test_get_welcome_image_defaults_to_packaged_asset(ctx) -> None:
    client, _maker = ctx
    r = await client.get("/api/admin/settings/welcome-image")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
    packaged = media._DEFAULT_WELCOME_IMAGE_PATH.read_bytes()
    assert len(packaged) > 0
    assert r.content == packaged


async def test_upload_rejects_bad_content_type(ctx) -> None:
    client, _maker = ctx
    r = await client.post(
        "/api/admin/settings/welcome-image",
        files={"file": ("notes.txt", b"this is plain text, not an image at all", "image/jpeg")},
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"]["code"] == "validation_error"
    assert "unsupported" in body["error"]["message"].lower()

    # A lying Content-Type header didn't help it in — the sniff runs on the bytes.
    default_still_served = await client.get("/api/admin/settings/welcome-image")
    assert default_still_served.content == media._DEFAULT_WELCOME_IMAGE_PATH.read_bytes()


async def test_upload_rejects_oversized_file(ctx) -> None:
    client, _maker = ctx
    oversized = _fake_jpeg(media.MAX_WELCOME_IMAGE_BYTES + 1)

    r = await client.post(
        "/api/admin/settings/welcome-image",
        files={"file": ("huge.jpg", oversized, "image/jpeg")},
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"]["code"] == "validation_error"
    assert "too large" in body["error"]["message"].lower()


async def test_replace_resets_cached_file_id(ctx) -> None:
    client, maker = ctx
    async with maker() as s:
        await settings_svc.set_value(
            s, media.WELCOME_IMAGE_FILE_ID_SETTING, "AgACA-stale-file-id-000"
        )
        await s.commit()

    r = await client.post(
        "/api/admin/settings/welcome-image",
        files={"file": ("coverage.png", _PNG_MAGIC + b"\x00" * 64, "image/png")},
    )
    assert r.status_code == 200, r.text

    async with maker() as s:
        row = await s.get(AppSetting, media.WELCOME_IMAGE_FILE_ID_SETTING)
        assert row is None, "a stale file_id must be cleared the moment the image is replaced"


# ── bot send path: cache use, fallback, and re-cache ─────────────────────────


class _FakeMessage:
    """Stands in for aiogram's Message — only the two methods _send_welcome_photo calls."""

    def __init__(self) -> None:
        self.answer = AsyncMock()
        self.answer_photo = AsyncMock()


def _sent_photo(file_id: str) -> AsyncMock:
    sent = AsyncMock()
    sent.photo = [AsyncMock(file_id=file_id)]
    return sent


@pytest_asyncio.fixture
async def bot_session_factory(engine, monkeypatch):
    """Redirects app.bot.handlers.start's SessionFactory at the isolated test database.

    _send_welcome_photo opens its own session (SessionFactory() at module scope) rather
    than taking one as a parameter — same as cmd_start already did before this change.
    Patched where the name is looked up (app.bot.handlers.start), not where it's defined,
    per the usual mock.patch rule.
    """
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.bot.handlers.start.SessionFactory", maker)
    return maker


async def test_send_welcome_photo_uses_cached_file_id(bot_session_factory) -> None:
    from app.bot.handlers.start import _send_welcome_photo

    message = _FakeMessage()
    await _send_welcome_photo(message, keyboard=object(), cached_file_id="AgACA-cached-good")

    message.answer_photo.assert_awaited_once()
    args, _kwargs = message.answer_photo.call_args
    assert args[0] == "AgACA-cached-good"  # sent by id — no bytes read, no re-upload
    message.answer.assert_not_awaited()  # caption fit on the photo — no separate text message


async def test_send_welcome_photo_falls_back_and_recaches_on_stale_id(
    bot_session_factory,
) -> None:
    from aiogram.types import BufferedInputFile
    from app.bot.handlers.start import _send_welcome_photo

    message = _FakeMessage()
    message.answer_photo.side_effect = [
        Exception("Telegram: file_id not found"),
        _sent_photo("AgACA-fresh-upload"),
    ]

    await _send_welcome_photo(message, keyboard=object(), cached_file_id="AgACA-stale")

    assert message.answer_photo.await_count == 2
    first_args, _ = message.answer_photo.await_args_list[0]
    assert first_args[0] == "AgACA-stale"
    second_args, _ = message.answer_photo.await_args_list[1]
    assert isinstance(second_args[0], BufferedInputFile)

    # The freshly-sent photo's id is now cached — the next /start won't re-upload bytes.
    async with bot_session_factory() as s:
        cached = await settings_svc.get(s, media.WELCOME_IMAGE_FILE_ID_SETTING)
        assert cached == "AgACA-fresh-upload"


async def test_send_welcome_photo_falls_back_to_text_when_photo_fails_outright(
    bot_session_factory,
) -> None:
    from app.bot.handlers.start import _send_welcome_photo

    message = _FakeMessage()
    message.answer_photo.side_effect = Exception("Telegram is unreachable")

    await _send_welcome_photo(message, keyboard=object(), cached_file_id=None)

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    assert "BM USA Proxy" in args[0]
    assert kwargs["reply_markup"] is not None  # buttons ride with the text, not lost

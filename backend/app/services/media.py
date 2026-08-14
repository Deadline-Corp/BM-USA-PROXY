"""media_assets — the one binary asset the bot needs.

Exactly one row today: the welcome-image sent as a photo with /start's greeting (see
bot/handlers/start.py). Not a general media library — the task this shipped for asked for
one replaceable asset, not a table of arbitrary uploads, so there is no list/delete here,
only get/set keyed by a constant.

Storage, not the filesystem: Railway's container disk is ephemeral, so anything an
operator uploads at runtime has to live in Postgres to survive the next deploy. The
packaged default (assets/welcome_coverage.jpg) ships inside the app image instead — read
from disk only when no operator upload exists yet, since it never changes at runtime and
shipping it as a git-tracked file is simpler than seeding a database row for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting, MediaAsset

WELCOME_IMAGE_KEY = "welcome_image"

# app_settings key caching the Telegram file_id of the last-sent welcome photo. Deleted by
# set_welcome_image() below in the same call that saves a new upload — a stale id is a
# pointer to bytes an operator just replaced, and Telegram would happily keep resending the
# old picture forever from cache if this weren't cleared alongside it.
WELCOME_IMAGE_FILE_ID_SETTING = "welcome_image_file_id"

MAX_WELCOME_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB — comfortably above a coverage-map JPEG/PNG

_DEFAULT_WELCOME_IMAGE_PATH = (
    Path(__file__).resolve().parents[1] / "assets" / "welcome_coverage.jpg"
)
_DEFAULT_WELCOME_IMAGE_CONTENT_TYPE = "image/jpeg"

# Sniffed off the file's own bytes, never off the client-supplied Content-Type header — a
# multipart request can claim anything there. Order doesn't matter: none of these three
# prefixes can ever match another's.
_MAGIC_PREFIXES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


def sniff_image_content_type(data: bytes) -> str | None:
    """The real content type, read off the file's magic bytes. None if it isn't one of the
    three types the welcome-image upload accepts (JPEG, PNG, WebP).
    """
    for prefix, content_type in _MAGIC_PREFIXES:
        if data.startswith(prefix):
            return content_type
    # WebP is a RIFF container: 'RIFF' + 4-byte size + 'WEBP', so the tag sits at offset 8.
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass(frozen=True)
class ImageAsset:
    content_type: str
    data: bytes


def _default_welcome_image() -> ImageAsset:
    return ImageAsset(
        content_type=_DEFAULT_WELCOME_IMAGE_CONTENT_TYPE,
        data=_DEFAULT_WELCOME_IMAGE_PATH.read_bytes(),
    )


async def get_welcome_image(session: AsyncSession) -> ImageAsset:
    """The image /start's greeting sends: the operator's upload if one exists, the packaged
    coverage map otherwise. Never raises — the default ships inside the app image, so there
    is always something to return.
    """
    row = await session.get(MediaAsset, WELCOME_IMAGE_KEY)
    if row is not None:
        return ImageAsset(content_type=row.content_type, data=row.data)
    return _default_welcome_image()


async def set_welcome_image(
    session: AsyncSession, *, content_type: str, data: bytes, admin_id: int | None = None
) -> None:
    """Save the operator's upload and drop the cached file_id in the same breath — see
    WELCOME_IMAGE_FILE_ID_SETTING above for why the two have to move together.
    """
    stmt = insert(MediaAsset).values(
        key=WELCOME_IMAGE_KEY, content_type=content_type, data=data, updated_by=admin_id
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={
            "content_type": stmt.excluded.content_type,
            "data": stmt.excluded.data,
            "updated_by": admin_id,
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    await session.execute(
        delete(AppSetting).where(AppSetting.key == WELCOME_IMAGE_FILE_ID_SETTING)
    )

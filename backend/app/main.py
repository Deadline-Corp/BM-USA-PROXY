"""FastAPI application factory: REST + webhooks + (Stage 2) SPA static hosting."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.errors import DomainError, domain_error_handler
from app.core.logging import RequestIdMiddleware, configure_logging, log


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.env, traces_sample_rate=0.1)
    log.info("api.startup", env=settings.env)
    yield
    log.info("api.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(title="BM USA Proxy API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]

    from app.api.health import router as health_router
    from app.api.twa.router import router as twa_router
    from app.api.webhooks import router as webhooks_router

    app.include_router(health_router)
    app.include_router(twa_router)
    app.include_router(webhooks_router)

    _register_admin(app)
    _register_telegram_webhook(app)
    return app


def _register_admin(app: FastAPI) -> None:
    try:
        from app.api.admin.router import router as admin_router
    except ModuleNotFoundError:
        return
    app.include_router(admin_router)


def _register_telegram_webhook(app: FastAPI) -> None:
    """POST /webhooks/telegram — rejects requests without the secret token."""

    @app.post("/webhooks/telegram")
    async def telegram_webhook(request: Request) -> Response:
        from app.bot.factory import get_bot, get_dispatcher

        bot = get_bot()
        if bot is None:
            return JSONResponse({"ok": False, "detail": "bot not configured"}, status_code=503)

        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(secret, settings.bot_webhook_secret):
            return JSONResponse({"ok": False}, status_code=403)

        from aiogram.types import Update

        update = Update.model_validate(await request.json(), context={"bot": bot})
        await get_dispatcher().feed_update(bot, update)
        return JSONResponse({"ok": True})


app = create_app()

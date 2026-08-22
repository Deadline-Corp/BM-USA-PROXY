"""FastAPI application factory: REST + webhooks + (Stage 2) SPA static hosting."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

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
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.public_base_url],  # explicit allowlist, never "*"
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]

    @app.middleware("http")
    async def _security_headers(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if settings.env != "local":  # staging + prod are served over HTTPS
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        # The operator console must never be framed (clickjacking). The Telegram
        # mini-app at /app is intentionally left frameable — Telegram embeds it.
        if request.url.path.startswith("/admin"):
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        return response

    from app.api.health import router as health_router
    from app.api.pay import router as pay_router
    from app.api.twa.router import router as twa_router
    from app.api.webhooks import router as webhooks_router

    app.include_router(health_router)
    app.include_router(pay_router)
    app.include_router(twa_router)
    app.include_router(webhooks_router)

    _register_admin(app)
    _register_telegram_webhook(app)
    _mount_spas(app)
    return app


def _mount_spas(app: FastAPI) -> None:
    """Serve the built SPAs at /app (mini-app) and /admin, if their dist/ is present.

    Candidate roots cover local dev (../frontend/<x>/dist) and the Docker image
    (/static/<x>) where the multi-stage build copies the bundles. SPAStaticFiles
    falls back to index.html on a 404 so client-side routes (e.g. /admin/requests)
    survive a direct load or refresh instead of returning a raw 404.
    """
    import os

    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.staticfiles import StaticFiles
    from starlette.types import Scope

    class SPAStaticFiles(StaticFiles):
        """Serve the SPA, and be explicit about what may be cached.

        Starlette sends only an ETag and leaves the policy to the client's heuristics — and
        a Telegram WebView's heuristics hold the entry document long enough that a deploy
        does not reach the buyer at all. That failure is invisible from our side: the new
        bundle is on the server, verified by hash, while the phone still runs the old one.

        Vite fingerprints every asset filename, so assets are safe to keep forever and the
        document naming them must be revalidated every time. `no-cache` means "ask first",
        not "don't store" — the ETag turns that question into a free 304.
        """

        async def get_response(self, path: str, scope: Scope) -> Response:
            served = path
            try:
                response = await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                if exc.status_code != 404:
                    raise
                served = "index.html"
                response = await super().get_response("index.html", scope)
            # Keyed on what was actually served, not what was asked for: a missing
            # `assets/…` file falls back to the HTML, and marking that immutable would
            # pin a stale document under an asset URL for a year.
            if served.startswith("assets/"):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "no-cache"
            return response

    for mount, name in (("/app", "miniapp"), ("/admin", "admin")):
        for root in (f"../frontend/{name}/dist", f"/static/{name}"):
            if os.path.isdir(root):
                app.mount(mount, SPAStaticFiles(directory=root, html=True), name=name)
                break


def _register_admin(app: FastAPI) -> None:
    try:
        from app.api.admin.router import router as admin_router
    except ModuleNotFoundError as exc:
        log.warning("admin.router.unavailable", error=str(exc))
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

        # Deduplicate by update_id: Telegram retries a delivery that did not get a 200
        # within its timeout, and the same update can arrive 2–3 times. Without this every
        # retry became a duplicate message in the thread, a duplicate operator alert, and a
        # duplicate AI answer. SET NX with a 24h TTL is enough — update_id is unique per
        # bot and monotonic, so a seen id will never come back legitimately.
        update_id = getattr(update, "update_id", None)
        if update_id is not None:
            from app.core.redis import redis_client

            dedup_key = f"tg:upd:{update_id}"
            if not await redis_client.set(dedup_key, "1", nx=True, ex=86400):
                return JSONResponse({"ok": True})  # already processed — ack and drop

        await get_dispatcher().feed_update(bot, update)
        return JSONResponse({"ok": True})


app = create_app()

"""iproxy.online Console API client + IproxyProvisioner (Stage 3).

Endpoints per research (02_iProxy_API_and_crypto_research / 06 §A1). Response SHAPES
must be confirmed against the live API with the client's key (task INT-1.1) — the parsing
here is defensive and centralised in `_parse_proxy_access` so it's a one-place fix.

Auth: Bearer <IPROXY_API_KEY> (Console key = whole account).
Rate limits are undocumented → a token-bucket throttle + bounded retries on 429/5xx.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import log
from app.services.provisioning.base import IssuedProxy, Provisioner


class IproxyError(Exception):
    """Base for iproxy client errors."""


class IproxyAuthError(IproxyError):
    """401/403 — bad/expired key. Alert, do not retry."""


class IproxyNotFound(IproxyError):
    """404 — connection/access not on iproxy (inventory drift)."""


class IproxyRateLimited(IproxyError):
    """429 — throttled."""


class IproxyUnavailable(IproxyError):
    """5xx / timeout — transient, retryable."""


class IproxyBadRequest(IproxyError):
    """4xx we didn't expect — likely a bug in our request."""


class _TokenBucket:
    """Simple async token bucket (default 5 req/s)."""

    def __init__(self, rate: float = 5.0) -> None:
        self._interval = 1.0 / rate
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            wait = self._next - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = loop.time()
            self._next = max(now, self._next) + self._interval


class IproxyClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        rate: float = 5.0,
        max_retries: int = 3,
    ) -> None:
        self._key = api_key or settings.iproxy_api_key or ""
        self._base = (base_url or settings.iproxy_base_url).rstrip("/")
        self._bucket = _TokenBucket(rate)
        self._max_retries = max_retries

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}

    async def _request(self, method: str, path: str, *, json: Any = None) -> Any:
        url = f"{self._base}{path}"
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            await self._bucket.acquire()
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.request(method, url, headers=self._headers(), json=json)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = IproxyUnavailable(str(exc))
                await asyncio.sleep(0.5 * (2**attempt))
                continue

            if resp.status_code in (401, 403):
                raise IproxyAuthError(f"{resp.status_code} {resp.text[:200]}")
            if resp.status_code == 404:
                raise IproxyNotFound(path)
            if resp.status_code == 429:
                last_exc = IproxyRateLimited("429")
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            if resp.status_code >= 500:
                last_exc = IproxyUnavailable(f"{resp.status_code}")
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            if resp.status_code >= 400:
                raise IproxyBadRequest(f"{resp.status_code} {resp.text[:200]}")
            return resp.json() if resp.content else None
        raise last_exc or IproxyUnavailable("exhausted retries")

    # ── operations (paths per research; confirm shapes at INT-1.1) ──────
    async def list_connections(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/console/v1/connection")
        return data if isinstance(data, list) else data.get("items", [])

    async def connection_status(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/console/v1/connection-status")
        return data if isinstance(data, list) else data.get("items", [])

    async def create_proxy_access(
        self, connection_id: str, *, expires_at_iso: str
    ) -> dict[str, Any]:
        data = await self._request(
            "POST",
            f"/api/console/v1/connection/{connection_id}/proxy-access",
            json={"expiresAt": expires_at_iso, "description": "bm-usa-proxy"},
        )
        return data if isinstance(data, dict) else {}

    async def list_proxy_access(self, connection_id: str) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", f"/api/console/v1/connection/{connection_id}/proxy-access"
        )
        return data if isinstance(data, list) else data.get("items", [])

    async def delete_proxy_access(self, connection_id: str, proxy_access_id: str) -> None:
        await self._request(
            "DELETE",
            f"/api/console/v1/connection/{connection_id}/proxy-access/{proxy_access_id}",
        )

    async def change_ip(self, connection_id: str) -> None:
        await self._request(
            "POST",
            f"/api/console/v1/connection/{connection_id}/command-push",
            json={"command": "changeip"},
        )


def _parse_proxy_access(raw: dict[str, Any]) -> IssuedProxy:
    """Map an iproxy proxy-access payload → our IssuedProxy. ADJUST at INT-1.1."""
    return IssuedProxy(
        iproxy_access_id=str(raw.get("id") or raw.get("proxyAccessId") or ""),
        credentials={
            "host": raw.get("host") or raw.get("ip"),
            "http_port": raw.get("httpPort") or raw.get("http_port"),
            "socks5_port": raw.get("socksPort") or raw.get("socks5_port"),
            "login": raw.get("login") or raw.get("username"),
            "password": raw.get("password"),
            "rotation_link": raw.get("changeIpUrl") or raw.get("rotationLink"),
        },
    )


class IproxyProvisioner(Provisioner):
    name = "iproxy"

    def __init__(self, client: IproxyClient | None = None) -> None:
        self._client = client or IproxyClient()

    async def issue(self, *, iproxy_connection_id: str, duration_minutes: int) -> IssuedProxy:
        from datetime import UTC, datetime, timedelta

        expires = (datetime.now(UTC) + timedelta(minutes=duration_minutes)).isoformat()
        raw = await self._client.create_proxy_access(
            iproxy_connection_id, expires_at_iso=expires
        )
        issued = _parse_proxy_access(raw)
        log.info("iproxy.issued", connection=iproxy_connection_id, access=issued.iproxy_access_id)
        return issued

    async def revoke(self, *, iproxy_connection_id: str, iproxy_access_id: str) -> None:
        with contextlib.suppress(IproxyNotFound):  # already gone — fine
            await self._client.delete_proxy_access(iproxy_connection_id, iproxy_access_id)

    async def rotate_ip(self, *, iproxy_connection_id: str) -> None:
        await self._client.change_ip(iproxy_connection_id)

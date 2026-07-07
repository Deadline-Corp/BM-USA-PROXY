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
from app.core.errors import ProvisioningError
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
        if isinstance(data, list):
            return data
        return data.get("connections", []) if isinstance(data, dict) else []

    async def connection_status(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/console/v1/connection-status")
        if isinstance(data, list):
            return data
        return data.get("connections", []) if isinstance(data, dict) else []

    async def create_proxy_access(
        self, connection_id: str, *, listen_service: str = "http"
    ) -> dict[str, Any]:
        # iproxy proxy-access: userpass auth, one access per protocol (http/socks5).
        # No iproxy-side expiry — lifetime is enforced our side (Access.expires_at) and
        # the expiry sweeper deletes the access when it lapses.
        data = await self._request(
            "POST",
            f"/api/console/v1/connection/{connection_id}/proxy-access",
            json={
                "auth_type": "userpass",
                "listen_service": listen_service,
                "description": "bm-usa-proxy",
            },
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
            json={"action": "changeip"},
        )


def _parse_proxy_access(raw: dict[str, Any]) -> IssuedProxy:
    """Map an iproxy proxy-access payload → our IssuedProxy.

    Confirmed live shape (2026-07-07): {"id", "auth": {"login", "password"},
    "hostname", "ip", "port", "listen_service"}. `hostname` is the durable proxy
    endpoint (c_fqdn); `ip` is the current mobile exit IP (informational). Rotation
    is a per-connection command, so there is no per-access rotation link.
    """
    auth = raw.get("auth") or {}
    port = raw.get("port")
    service = raw.get("listen_service") or "http"
    return IssuedProxy(
        iproxy_access_id=str(raw.get("id") or ""),
        credentials={
            "host": raw.get("hostname") or raw.get("ip"),
            "http_port": port if service == "http" else None,
            "socks5_port": port if service == "socks5" else None,
            "login": auth.get("login"),
            "password": auth.get("password"),
            "listen_service": service,
            "exit_ip": raw.get("ip"),
            "rotation_link": None,
        },
    )


class IproxyProvisioner(Provisioner):
    name = "iproxy"

    def __init__(self, client: IproxyClient | None = None) -> None:
        self._client = client or IproxyClient()

    async def issue(self, *, iproxy_connection_id: str, duration_minutes: int) -> IssuedProxy:
        # Lifetime is enforced our side (Access.expires_at); iproxy access has no expiry.
        try:
            raw = await self._client.create_proxy_access(iproxy_connection_id)
        except IproxyError as exc:
            raise ProvisioningError(f"iproxy issue failed: {exc}") from exc
        issued = _parse_proxy_access(raw)
        if not issued.iproxy_access_id or not issued.credentials.get("host"):
            raise ProvisioningError(f"malformed iproxy proxy-access response: {sorted(raw)[:8]}")
        log.info("iproxy.issued", connection=iproxy_connection_id, access=issued.iproxy_access_id)
        return issued

    async def revoke(self, *, iproxy_connection_id: str, iproxy_access_id: str) -> None:
        with contextlib.suppress(IproxyNotFound):  # already gone — fine
            await self._client.delete_proxy_access(iproxy_connection_id, iproxy_access_id)

    async def rotate_ip(self, *, iproxy_connection_id: str) -> None:
        try:
            await self._client.change_ip(iproxy_connection_id)
        except IproxyError as exc:
            raise ProvisioningError(f"iproxy rotate failed: {exc}") from exc

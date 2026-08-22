"""iproxy.online Console API client + IproxyProvisioner (Stage 3).

Endpoints per research (02_iProxy_API_and_crypto_research / 06 §A1). Response SHAPES
must be confirmed against the live API with the client's key (task INT-1.1) — the parsing
here is defensive and centralised in `_parse_proxy_access` so it's a one-place fix.

Auth: Bearer <IPROXY_API_KEY> (Console key = whole account).
Rate limits are undocumented → a token-bucket throttle + bounded retries on 429/5xx.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import ProvisioningError
from app.core.logging import log
from app.services.provisioning.base import ExitIp, IssuedProxy, Provisioner


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
        # One shared client for the lifetime of this IproxyClient, instead of a new
        # httpx.AsyncClient per _request call. Connection pooling reduces latency and
        # avoids the TLS handshake overhead on every provision/revoke/rotate call.
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}

    async def _request(self, method: str, path: str, *, json: Any = None) -> Any:
        url = f"{self._base}{path}"
        client = self._get_client()
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            await self._bucket.acquire()
            try:
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
        """Every proxy-access on this connection, whoever created it.

        The envelope key is `proxy_accesses`, confirmed against the live API 2026-08-17.
        This used to read `items`, which is not a key iproxy has ever returned — so it
        answered "no accesses" for every connection, always, including phones plainly
        showing credentials in the iproxy console. Everything built on it (external-hold
        detection) therefore saw an empty account and reported nothing.

        The list form is kept for safety, not because it has been observed.
        """
        data = await self._request(
            "GET", f"/api/console/v1/connection/{connection_id}/proxy-access"
        )
        if isinstance(data, list):
            return data
        return data.get("proxy_accesses", []) if isinstance(data, dict) else []

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

    async def get_connection(self, connection_id: str) -> dict[str, Any]:
        data = await self._request("GET", f"/api/console/v1/connection/{connection_id}")
        return data if isinstance(data, dict) else {}

    # ── action links (buyer-facing "rotate my IP" URL) ───────────────────
    # Confirmed against the live API 2026-08-14 — none of this is documented:
    #   POST   /connection/{id}/actionlinks  {"action": "changeip"}  -> {"id"}
    #   GET    /connection/{id}/actionlinks  -> {"action_links": [{id, link, ...}]}
    #   DELETE /connection/{id}/actionlinks/{link_id}
    # The flat /actionlinks/{id} form answers 404 on DELETE — must be connection-scoped.
    # POST returns the id ONLY, so the URL itself has to be read back from the list;
    # composing it from a hardcoded i.fxdx.in host would break the day they move domains.
    # Each connection is capped at plan_info.features.max_ip_links_per_connection (15).

    async def create_action_link(self, connection_id: str, *, action: str = "changeip") -> str:
        data = await self._request(
            "POST",
            f"/api/console/v1/connection/{connection_id}/actionlinks",
            json={"action": action, "comment": "bm-usa-proxy"},
        )
        return str((data or {}).get("id") or "") if isinstance(data, dict) else ""

    async def list_action_links(self, connection_id: str) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", f"/api/console/v1/connection/{connection_id}/actionlinks"
        )
        if isinstance(data, list):
            return data
        return data.get("action_links", []) if isinstance(data, dict) else []

    async def delete_action_link(self, connection_id: str, link_id: str) -> None:
        await self._request(
            "DELETE",
            f"/api/console/v1/connection/{connection_id}/actionlinks/{link_id}",
        )

    # ── VPN configs (OpenVPN / WireGuard) ───────────────────────────────
    # Verified against the live API 2026-08-12, because the docs do not describe this:
    # OpenVPN is documented, **WireGuard is not documented at all** — no endpoint, no
    # page (`/docs-api-wireguard` is a 404) — yet `wg-access` exists and behaves exactly
    # like `ovpn-access`. Everything below was confirmed by calling it: create → 201,
    # config → 200 with a real file, delete → 204.
    #
    # A VPN config is a resource of the CONNECTION, a sibling of proxy-access rather than
    # a `listen_service` variant of it — that enum accepts only http and socks5.
    #
    # DNS is deliberately not sent. Measured: creating with no `dns` field still produces
    # a config containing `DNS = <the server's own resolver>`, so iproxy fills the right
    # one per connection. Passing a value would replace a per-server address with one
    # constant and hand the wrong resolver to phones on other subnets.

    @staticmethod
    def _vpn_segment(kind: str) -> str:
        if kind not in ("ovpn", "wg"):
            raise IproxyBadRequest(f"unknown VPN kind {kind!r}")
        return f"{kind}-access"

    async def create_vpn_access(
        self, connection_id: str, *, kind: str, name: str
    ) -> dict[str, Any]:
        data = await self._request(
            "POST",
            f"/api/console/v1/connection/{connection_id}/{self._vpn_segment(kind)}",
            json={"name": name[:64], "description": "bm-usa-proxy"},
        )
        return data if isinstance(data, dict) else {}

    async def get_vpn_config(self, connection_id: str, *, kind: str, vpn_access_id: str) -> bytes:
        """The config file itself, decoded. Raises if the response is not what we expect."""
        seg = self._vpn_segment(kind)
        data = await self._request(
            "GET",
            f"/api/console/v1/connection/{connection_id}/{seg}/{vpn_access_id}/config",
        )
        encoded = (data or {}).get("config_base64") if isinstance(data, dict) else None
        if not encoded:
            raise IproxyBadRequest(f"{kind} config response had no config_base64")
        try:
            return base64.b64decode(encoded)
        except (ValueError, binascii.Error) as exc:
            raise IproxyBadRequest(f"{kind} config was not valid base64: {exc}") from None

    async def delete_vpn_access(self, connection_id: str, *, kind: str, vpn_access_id: str) -> None:
        # Must be the connection-scoped path. The flat `/{kind}-access/{id}` form is
        # documented for OpenVPN but answers 404 — measured, both protocols.
        await self._request(
            "DELETE",
            f"/api/console/v1/connection/{connection_id}/{self._vpn_segment(kind)}/{vpn_access_id}",
        )


def _parse_proxy_access(raw: dict[str, Any]) -> IssuedProxy:
    """Map an iproxy proxy-access payload → our IssuedProxy.

    Confirmed live shape (2026-07-07): {"id", "auth": {"login", "password"},
    "hostname", "ip", "port", "listen_service"}. `hostname` is the durable proxy
    endpoint (c_fqdn); `ip` is the current mobile exit IP (informational).

    One payload describes ONE protocol. A buyer gets both http and socks5, which are
    two separate iproxy accesses with **different ports and different credentials** —
    so `login`/`password` here are the ones for `listen_service`, and the sibling
    protocol's are merged in by `_merge_socks5` afterwards.
    """
    auth = raw.get("auth") or {}
    port = raw.get("port")
    service = raw.get("listen_service") or "http"
    is_http = service == "http"
    login, password = auth.get("login"), auth.get("password")
    return IssuedProxy(
        iproxy_access_id=str(raw.get("id") or ""),
        credentials={
            "host": raw.get("hostname") or raw.get("ip"),
            "http_port": port if is_http else None,
            "http_login": login if is_http else None,
            "http_password": password if is_http else None,
            "socks5_port": None if is_http else port,
            "socks5_login": None if is_http else login,
            "socks5_password": None if is_http else password,
            # Kept as the http pair: every existing access in the database was issued
            # with these two keys and the UI still reads them as the primary credential.
            "login": login,
            "password": password,
            "listen_service": service,
            "exit_ip": raw.get("ip"),
            "rotation_link": None,
        },
    )


def _merge_socks5(issued: IssuedProxy, raw: dict[str, Any]) -> None:
    """Fold a socks5 proxy-access payload into an already-parsed http access."""
    auth = raw.get("auth") or {}
    issued.socks5_access_id = str(raw.get("id") or "") or None
    issued.credentials["socks5_port"] = raw.get("port")
    issued.credentials["socks5_login"] = auth.get("login")
    issued.credentials["socks5_password"] = auth.get("password")


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

        # socks5 and the rotation link are deliberately best-effort. The buyer has
        # already paid and the http proxy above is live and usable; failing the whole
        # issue over a second, optional resource would take away what already works.
        # A miss is logged and shows up as an empty field on the access screen.
        try:
            socks_raw = await self._client.create_proxy_access(
                iproxy_connection_id, listen_service="socks5"
            )
            _merge_socks5(issued, socks_raw)
        except IproxyError as exc:
            log.warning("iproxy.socks5_failed", connection=iproxy_connection_id, error=str(exc))

        try:
            issued.action_link_id = await self._client.create_action_link(iproxy_connection_id)
            issued.credentials["rotation_link"] = await self._action_link_url(
                iproxy_connection_id, issued.action_link_id
            )
        except IproxyError as exc:
            log.warning("iproxy.actionlink_failed", connection=iproxy_connection_id, error=str(exc))

        log.info(
            "iproxy.issued",
            connection=iproxy_connection_id,
            access=issued.iproxy_access_id,
            socks5=issued.socks5_access_id,
            link=issued.action_link_id,
        )
        return issued

    async def _action_link_url(self, connection_id: str, link_id: str) -> str | None:
        """Read the URL back — POST answers with the id alone."""
        if not link_id:
            return None
        for link in await self._client.list_action_links(connection_id):
            if str(link.get("id")) == link_id:
                url = link.get("link")
                return str(url) if url else None
        return None

    async def revoke(
        self,
        *,
        iproxy_connection_id: str,
        iproxy_access_id: str,
        socks5_access_id: str | None = None,
        action_link_id: str | None = None,
    ) -> None:
        # Every resource is removed independently: one that is already gone (404) or
        # fails must not strand the others on the connection. A leftover socks5 access
        # or rotation link would keep working for a customer whose access we revoked.
        for access_id in (iproxy_access_id, socks5_access_id):
            if not access_id:
                continue
            with contextlib.suppress(IproxyError):  # already gone / transient — best-effort
                await self._client.delete_proxy_access(iproxy_connection_id, access_id)
        if action_link_id:
            with contextlib.suppress(IproxyError):
                await self._client.delete_action_link(iproxy_connection_id, action_link_id)

    async def create_vpn_access(
        self, *, iproxy_connection_id: str, kind: str, name: str
    ) -> str:
        raw = await self._client.create_vpn_access(iproxy_connection_id, kind=kind, name=name)
        # The response nests under the resource name on some shapes and is flat on others;
        # take whichever carries the id rather than assuming. `raw` is {} on an empty body,
        # so both branches are dicts and neither can be None.
        nested = raw.get(f"{kind}_access")
        inner: dict[str, Any] = nested if isinstance(nested, dict) else raw
        vpn_id = str(inner.get("id") or "")
        if not vpn_id:
            raise ProvisioningError(f"iproxy {kind} create returned no id: {sorted(raw)[:6]}")
        return vpn_id

    async def vpn_config(
        self, *, iproxy_connection_id: str, kind: str, vpn_access_id: str
    ) -> bytes:
        try:
            return await self._client.get_vpn_config(
                iproxy_connection_id, kind=kind, vpn_access_id=vpn_access_id
            )
        except IproxyError as exc:
            raise ProvisioningError(f"iproxy {kind} config fetch failed: {exc}") from exc

    async def delete_vpn_access(
        self, *, iproxy_connection_id: str, kind: str, vpn_access_id: str
    ) -> None:
        with contextlib.suppress(IproxyNotFound):  # already gone — fine
            await self._client.delete_vpn_access(
                iproxy_connection_id, kind=kind, vpn_access_id=vpn_access_id
            )

    async def rotate_ip(self, *, iproxy_connection_id: str) -> None:
        try:
            await self._client.change_ip(iproxy_connection_id)
        except IproxyError as exc:
            raise ProvisioningError(f"iproxy rotate failed: {exc}") from exc

    async def current_ip(self, *, iproxy_connection_id: str) -> str | None:
        return (await self.current_exit_ip(iproxy_connection_id=iproxy_connection_id)).address

    async def current_exit_ip(self, *, iproxy_connection_id: str) -> ExitIp:
        # Same GET as current_ip used to make on its own — app_data carries both the exit
        # IP and ip_city in one response, so a caller that also needs the city (accesses.py,
        # lifecycle.py) never pays for a second request just to get it.
        try:
            data = await self._client.get_connection(iproxy_connection_id)
        except IproxyError:
            return ExitIp(address=None, city=None)
        app_data = data.get("app_data") or {}
        device = app_data.get("device_info") or {}
        ip = (device.get("ip_public") or {}).get("ipv4")
        city = app_data.get("ip_city")
        return ExitIp(address=str(ip) if ip else None, city=str(city) if city else None)

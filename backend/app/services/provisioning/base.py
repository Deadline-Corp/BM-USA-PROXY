"""Provisioner interface — MockProvisioner (Stage 2) → IproxyProvisioner (Stage 3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class IssuedProxy:
    # A buyer's access is three iproxy resources, not one: an http proxy-access, a
    # socks5 proxy-access (own port and own credentials), and a changeip action link.
    # All three ids are stored so revoke can take every one of them back down.
    iproxy_access_id: str  # the http access — the one that must exist
    credentials: dict  # host, {http,socks5}_{port,login,password}, rotation_link
    socks5_access_id: str | None = None
    action_link_id: str | None = None


@dataclass(slots=True)
class ExitIp:
    address: str | None
    city: str | None  # iproxy's app_data.ip_city, read off the same response as address


class Provisioner(Protocol):
    name: str

    async def issue(self, *, iproxy_connection_id: str, duration_minutes: int) -> IssuedProxy: ...

    async def revoke(
        self,
        *,
        iproxy_connection_id: str,
        iproxy_access_id: str,
        socks5_access_id: str | None = None,
        action_link_id: str | None = None,
    ) -> None: ...

    async def rotate_ip(self, *, iproxy_connection_id: str) -> None: ...

    async def current_ip(self, *, iproxy_connection_id: str) -> str | None: ...

    # Same provider call as current_ip, but carries the city alongside the address so a
    # caller that needs both — accesses.py::detail_for_user, lifecycle.py::rotate_ip —
    # never pays for a second request just to keep a connection's sold city current
    # between sync_pool passes.
    async def current_exit_ip(self, *, iproxy_connection_id: str) -> ExitIp: ...

    # VPN configs are a separate iproxy resource from the proxy access — see
    # services/vpn_configs.py for why they must be revoked explicitly.
    async def create_vpn_access(
        self, *, iproxy_connection_id: str, kind: str, name: str
    ) -> str: ...

    async def vpn_config(
        self, *, iproxy_connection_id: str, kind: str, vpn_access_id: str
    ) -> bytes: ...

    async def delete_vpn_access(
        self, *, iproxy_connection_id: str, kind: str, vpn_access_id: str
    ) -> None: ...

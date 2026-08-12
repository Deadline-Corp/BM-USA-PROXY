"""Provisioner interface — MockProvisioner (Stage 2) → IproxyProvisioner (Stage 3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class IssuedProxy:
    iproxy_access_id: str
    credentials: dict  # host, http_port, socks5_port, login, password, rotation_link


class Provisioner(Protocol):
    name: str

    async def issue(self, *, iproxy_connection_id: str, duration_minutes: int) -> IssuedProxy: ...

    async def revoke(self, *, iproxy_connection_id: str, iproxy_access_id: str) -> None: ...

    async def rotate_ip(self, *, iproxy_connection_id: str) -> None: ...

    async def current_ip(self, *, iproxy_connection_id: str) -> str | None: ...

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

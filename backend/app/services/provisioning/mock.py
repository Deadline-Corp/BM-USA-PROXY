"""MockProvisioner — fabricates realistic proxy credentials without calling iproxy."""

from __future__ import annotations

import secrets

from app.services.provisioning.base import IssuedProxy, Provisioner


class MockProvisioner(Provisioner):
    name = "mock"

    async def issue(self, *, iproxy_connection_id: str, duration_minutes: int) -> IssuedProxy:
        token = secrets.token_hex(4)
        octet = 1 + (hash(iproxy_connection_id) % 254)
        return IssuedProxy(
            iproxy_access_id=f"mock-acc-{token}",
            credentials={
                "host": f"104.28.{octet}.{1 + secrets.randbelow(254)}",
                "http_port": 8080,
                "socks5_port": 1080,
                "login": f"u{token}",
                "password": secrets.token_urlsafe(9),
                "rotation_link": f"https://mock.iproxy.local/rotate/{token}",
            },
        )

    async def revoke(self, *, iproxy_connection_id: str, iproxy_access_id: str) -> None:
        return None

    async def rotate_ip(self, *, iproxy_connection_id: str) -> None:
        return None

    async def current_ip(self, *, iproxy_connection_id: str) -> str | None:
        return None

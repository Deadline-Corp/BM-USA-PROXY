"""MockProvisioner — fabricates realistic proxy credentials without calling iproxy."""

from __future__ import annotations

import secrets

from app.services.provisioning.base import ExitIp, IssuedProxy, Provisioner


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

    async def current_exit_ip(self, *, iproxy_connection_id: str) -> ExitIp:
        return ExitIp(address=None, city=None)

    async def create_vpn_access(
        self, *, iproxy_connection_id: str, kind: str, name: str
    ) -> str:
        return f"mock-{kind}-{secrets.token_hex(4)}"

    async def vpn_config(
        self, *, iproxy_connection_id: str, kind: str, vpn_access_id: str
    ) -> bytes:
        # Shaped like the real thing so anything that parses or displays a config —
        # a test, a local run — sees the same structure it will see in production.
        if kind == "wg":
            lines = [
                "[Interface]",
                f"PrivateKey = {secrets.token_urlsafe(32)}",
                "Address = 10.190.0.2/32",
                "DNS = 10.190.0.1",
                "",
                "[Peer]",
                f"PublicKey = {secrets.token_urlsafe(32)}",
                f"Endpoint = mock-{vpn_access_id}.local:51820",
                "AllowedIPs = 0.0.0.0/0, ::/0",
                "PersistentKeepalive = 25",
            ]
        else:
            lines = [
                "client",
                "dev tun",
                "proto udp",
                f"remote mock-{vpn_access_id}.local 1194",
                "resolv-retry infinite",
                "nobind",
                "persist-key",
                "persist-tun",
            ]
        return ("\n".join(lines) + "\n").encode()

    async def delete_vpn_access(
        self, *, iproxy_connection_id: str, kind: str, vpn_access_id: str
    ) -> None:
        return None

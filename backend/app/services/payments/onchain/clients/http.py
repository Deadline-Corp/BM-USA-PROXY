"""Tiny async JSON-over-HTTP transport used by chain clients.

An injectable ``JsonHttp`` keeps clients unit-testable offline (tests pass a fake that
returns canned RPC responses); the default :class:`HttpxJson` wraps ``httpx.AsyncClient``.
"""

from __future__ import annotations

from typing import Any, Protocol


class JsonHttp(Protocol):
    async def get(
        self, url: str, *, params: dict | None = None, headers: dict | None = None
    ) -> Any: ...

    async def post(
        self, url: str, *, json: Any | None = None, headers: dict | None = None
    ) -> Any: ...

    async def aclose(self) -> None: ...


class HttpxJson:
    """Default transport. httpx is imported lazily so tests never require it."""

    def __init__(self, timeout: float = 15.0) -> None:
        import httpx

        self._client = httpx.AsyncClient(timeout=timeout)

    async def get(
        self, url: str, *, params: dict | None = None, headers: dict | None = None
    ) -> Any:
        resp = await self._client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def post(
        self, url: str, *, json: Any | None = None, headers: dict | None = None
    ) -> Any:
        resp = await self._client.post(url, json=json, headers=headers)
        # A JSON-RPC error is an answer, not a transport failure, whatever status code the
        # provider chose to wrap it in. Alchemy returns its "you asked for too many blocks"
        # refusal as HTTP 400 with the error in the body; raising on the status threw that
        # body away, so the caller's halve-the-range retry — written for exactly this
        # refusal — never saw it, and the Ethereum watcher sat dead for nine hours while a
        # customer's payment landed unnoticed. Hand the body back and let the RPC layer
        # raise its own typed error; a status with no JSON-RPC error in it still raises.
        if resp.is_error:
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001 — not JSON, so it really is a transport error
                body = None
            if isinstance(body, dict) and body.get("error"):
                return body
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()

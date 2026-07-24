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
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()

"""USD → crypto price oracle.

Stablecoins are pinned to 1.0 USD. Volatile assets are priced through an injectable
async source (default: CoinGecko) with a short in-process cache so that quoting a burst
of invoices does not hammer the price API. The rate is *locked* onto the invoice at
creation time so a later price move never changes what the buyer must pay.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal

from app.services.payments.onchain.assets import COINGECKO_IDS, AssetSpec

# usd price of one whole unit of the asset, keyed by coingecko id.
PriceSource = Callable[[str], Awaitable[Decimal]]


class PriceUnavailable(RuntimeError):
    """Raised when a volatile asset cannot be priced (invoice creation must fail)."""


@dataclass(frozen=True, slots=True)
class Quote:
    rate: Decimal          # USD per 1 whole unit of the asset
    crypto_amount: Decimal  # unrounded amount of asset for the requested USD


async def _coingecko_source(coingecko_id: str) -> Decimal:
    import httpx

    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": coingecko_id, "vs_currencies": "usd"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    try:
        return Decimal(str(data[coingecko_id]["usd"]))
    except (KeyError, TypeError) as exc:
        raise PriceUnavailable(f"coingecko returned no usd price for {coingecko_id}") from exc


class PriceOracle:
    def __init__(self, source: PriceSource | None = None, ttl_seconds: float = 30.0) -> None:
        self._source = source or _coingecko_source
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, Decimal]] = {}
        self._lock = asyncio.Lock()

    async def usd_price(self, spec: AssetSpec) -> Decimal:
        if spec.is_stable:
            return Decimal(1)
        coingecko_id = COINGECKO_IDS.get(spec.asset)
        if coingecko_id is None:
            raise PriceUnavailable(f"no price feed mapped for asset {spec.asset}")

        now = time.monotonic()
        cached = self._cache.get(coingecko_id)
        if cached is not None and now - cached[0] < self._ttl:
            return cached[1]

        async with self._lock:
            # re-check inside the lock — another coroutine may have refreshed it
            cached = self._cache.get(coingecko_id)
            if cached is not None and time.monotonic() - cached[0] < self._ttl:
                return cached[1]
            price = await self._source(coingecko_id)
            if price <= 0:
                raise PriceUnavailable(f"non-positive price for {coingecko_id}: {price}")
            self._cache[coingecko_id] = (time.monotonic(), price)
            return price

    async def quote(self, amount_usd: Decimal, spec: AssetSpec) -> Quote:
        rate = await self.usd_price(spec)
        return Quote(rate=rate, crypto_amount=amount_usd / rate)


# module-level default oracle (shared cache across invoice creations)
_default_oracle: PriceOracle | None = None


def get_oracle() -> PriceOracle:
    global _default_oracle
    if _default_oracle is None:
        _default_oracle = PriceOracle()
    return _default_oracle

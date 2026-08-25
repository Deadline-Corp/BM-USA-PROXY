"""USD → crypto price oracle.

Stablecoins are pinned to 1.0 USD. Volatile assets are priced through a chain: CoinGecko
first, a second exchange when it does not answer, and only then a very recent cached price.
The rate is *locked* onto the invoice at creation time so a later price move never changes
what the buyer must pay.

Why a chain rather than one source with a generous cache: a single unauthenticated feed
rate-limited us on Railway's shared egress IP, and every 429 became a failed checkout
(seen on production 2026-08-25). The obvious fix — serve an older cached price — is the
wrong one here. Crypto moves, and a price fifteen minutes stale during a rise means selling
the proxy for less than it costs us. A second live source keeps the quote current instead.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal

from app.core.errors import ServiceUnavailable
from app.services.payments.onchain.assets import COINGECKO_IDS, AssetSpec

log = logging.getLogger(__name__)

# usd price of one whole unit of the asset, keyed by coingecko id.
PriceSource = Callable[[str], Awaitable[Decimal]]

# How old the last good price may be before we stop offering it at all. Only ever reached
# when BOTH live sources are down at once, so it is a last resort rather than a cache.
# A minute, not fifteen: on a rising market a stale quote undercharges for the proxy, and
# refusing to quote is cheaper than selling below cost. Nikolay's call, 2026-08-25.
STALE_GRACE_SECONDS = 60.0


class PriceUnavailable(ServiceUnavailable):
    """We cannot price this asset right now. Please try again in a moment."""

    code = "price_unavailable"

    def __init__(self, detail: str) -> None:
        # Two audiences. The buyer gets the docstring; `detail` names which source failed
        # and how, and belongs in the log — "coingecko returned no usd price for ethereum"
        # tells a customer nothing and tells everybody else what we run on.
        self.detail = detail
        super().__init__(None)
        self.args = (detail,)


@dataclass(frozen=True, slots=True)
class Quote:
    rate: Decimal          # USD per 1 whole unit of the asset
    crypto_amount: Decimal  # unrounded amount of asset for the requested USD


async def _coingecko_source(coingecko_id: str) -> Decimal:
    import httpx

    from app.core.config import settings

    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": coingecko_id, "vs_currencies": "usd"}
    # Same host and path on the Demo plan — the key only changes which quota the call is
    # counted against, and ours was shared with everything else leaving Railway's IP.
    # Header, not query string: a key in a URL is printed into every access log it passes.
    key = (settings.coingecko_api_key or "").strip()
    headers = {"x-cg-demo-api-key": key} if key else None
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    try:
        return Decimal(str(data[coingecko_id]["usd"]))
    except (KeyError, TypeError) as exc:
        raise PriceUnavailable(f"coingecko returned no usd price for {coingecko_id}") from exc


# Kraken rather than Binance, which answers 451 from Railway's egress — measured from
# inside the running container, not assumed. Kraken quotes real USD pairs (not USDT
# proxies), needs no key, and covers every asset we sell.
_KRAKEN_PAIRS: dict[str, str] = {
    "bitcoin": "XBTUSD",
    "ethereum": "ETHUSD",
    "litecoin": "LTCUSD",
    "solana": "SOLUSD",
    "tron": "TRXUSD",
}


async def _kraken_source(coingecko_id: str) -> Decimal:
    import httpx

    pair = _KRAKEN_PAIRS.get(coingecko_id)
    if pair is None:
        raise PriceUnavailable(f"no kraken pair mapped for {coingecko_id}")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://api.kraken.com/0/public/Ticker", params={"pair": pair}
        )
        resp.raise_for_status()
        body = resp.json()
    # Kraken answers 200 with the failure inside the body.
    if body.get("error"):
        raise PriceUnavailable(f"kraken error for {pair}: {body['error']}")
    result = body.get("result") or {}
    if len(result) != 1:
        raise PriceUnavailable(f"kraken returned {len(result)} entries for {pair}")
    # Read the single entry without knowing Kraken's own name for it: they answer XBTUSD
    # as "XXBTZUSD" but SOLUSD as "SOLUSD", and keeping that table right is a second thing
    # to maintain for no gain when we only ever ask about one pair.
    ticker = next(iter(result.values()))
    try:
        return Decimal(str(ticker["c"][0]))  # c = last trade closed: [price, lot volume]
    except (KeyError, IndexError, TypeError) as exc:
        raise PriceUnavailable(f"kraken returned no last price for {pair}") from exc


async def _USE_DEFAULT_FALLBACK(_coingecko_id: str) -> Decimal:  # noqa: N802
    """Sentinel for "caller said nothing", distinct from an explicit ``None``.

    Never called — `PriceOracle.__init__` swaps it out. It is a function rather than a
    bare object only so the parameter keeps the `PriceSource` type.
    """
    raise AssertionError("sentinel fallback must be replaced in __init__")


class PriceOracle:
    def __init__(
        self,
        source: PriceSource | None = None,
        fallback: PriceSource | None = _USE_DEFAULT_FALLBACK,
        ttl_seconds: float = 30.0,
        stale_grace_seconds: float = STALE_GRACE_SECONDS,
    ) -> None:
        self._source = source or _coingecko_source
        # An injected primary means a unit test. It gets no live fallback unless one is
        # passed explicitly — otherwise a test that makes the primary fail would quietly
        # reach the real Kraken and start passing or failing on somebody else's uptime.
        if fallback is _USE_DEFAULT_FALLBACK:
            fallback = _kraken_source if source is None else None
        self._fallback = fallback
        self._ttl = ttl_seconds
        self._stale_grace = stale_grace_seconds
        self._cache: dict[str, tuple[float, Decimal]] = {}
        # (fetched_at, price) — the sanity baseline, and the last-resort quote.
        self._last_good: dict[str, tuple[float, Decimal]] = {}
        self._lock = asyncio.Lock()

    async def _live_price(self, coingecko_id: str) -> Decimal:
        """The first source that answers with a usable price. Raises when none do."""
        failures: list[str] = []
        for name, src in (("primary", self._source), ("fallback", self._fallback)):
            if src is None:
                continue
            try:
                price = await src(coingecko_id)
            except Exception as exc:
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            if price <= 0:
                failures.append(f"{name}: non-positive price {price}")
                continue
            if failures:
                # Worth a line: the primary being down is invisible from the outside once
                # the fallback covers for it, and it stays invisible until both are.
                log.warning(
                    "oracle.fallback_used", extra={"asset": coingecko_id, "why": failures}
                )
            return price
        raise PriceUnavailable(
            f"no source could price {coingecko_id} — " + "; ".join(failures)
        )

    def _recent_good(self, coingecko_id: str) -> Decimal | None:
        entry = self._last_good.get(coingecko_id)
        if entry is None:
            return None
        fetched_at, price = entry
        if time.monotonic() - fetched_at > self._stale_grace:
            return None
        return price

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
            try:
                price = await self._live_price(coingecko_id)
            except PriceUnavailable:
                # Both sources down at once. A price from the last minute is worth serving;
                # anything older is not, and refusing to quote beats quoting wrong.
                recent = self._recent_good(coingecko_id)
                if recent is not None:
                    log.warning("oracle.served_stale", extra={"asset": coingecko_id})
                    return recent
                raise
            # Sanity band: two sources with no bound still let a bogus 1000x quote turn a
            # $1000 order into a dust invoice. Reject a move beyond 5x from the last
            # accepted price (generous for real volatility between fetches).
            prev = self._last_good.get(coingecko_id)
            if prev is not None and not (prev[1] / 5 <= price <= prev[1] * 5):
                raise PriceUnavailable(
                    f"price for {coingecko_id} left the sanity band: {prev[1]} -> {price}"
                )
            stamped = time.monotonic()
            self._last_good[coingecko_id] = (stamped, price)
            self._cache[coingecko_id] = (stamped, price)
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

"""Unit tests for the price oracle (no network — a stub source is injected)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.services.payments.onchain.assets import get_spec
from app.services.payments.onchain.oracle import (
    STALE_GRACE_SECONDS,
    PriceOracle,
    PriceUnavailable,
)


async def test_stablecoin_is_pinned_and_never_calls_source() -> None:
    calls = {"n": 0}

    async def src(_cg: str) -> Decimal:
        calls["n"] += 1
        return Decimal("100")

    oracle = PriceOracle(source=src)
    quote = await oracle.quote(Decimal("10"), get_spec("USDT", "trc20"))
    assert quote.rate == Decimal(1)
    assert quote.crypto_amount == Decimal("10")
    assert calls["n"] == 0


async def test_volatile_priced_and_cached() -> None:
    calls = {"n": 0}

    async def src(_cg: str) -> Decimal:
        calls["n"] += 1
        return Decimal("100")

    oracle = PriceOracle(source=src, ttl_seconds=100)
    q1 = await oracle.quote(Decimal("10"), get_spec("BTC", "native"))
    q2 = await oracle.quote(Decimal("20"), get_spec("BTC", "native"))
    assert q1.rate == Decimal("100")
    assert q1.crypto_amount == Decimal("0.1")
    assert q2.crypto_amount == Decimal("0.2")
    assert calls["n"] == 1  # second call served from cache


async def test_non_positive_price_raises() -> None:
    async def bad(_cg: str) -> Decimal:
        return Decimal(0)

    oracle = PriceOracle(source=bad)
    with pytest.raises(PriceUnavailable):
        await oracle.usd_price(get_spec("ETH", "native"))


async def test_the_coingecko_key_rides_in_a_header_and_only_when_set(monkeypatch) -> None:
    """CoinGecko's Demo plan is the same host and path — the key is the whole difference.

    It moves our calls off the quota shared with everything else on Railway's egress IP,
    which is where the 429s came from that turned into failed checkouts. Two things this
    pins: the key travels as a header (in a query string it would be printed into every
    access log we or they keep), and no key means the call still goes out — the oracle
    must not start requiring a key it did not need yesterday.
    """
    import httpx
    from app.core.config import settings
    from app.services.payments.onchain import oracle as oracle_mod

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ethereum": {"usd": 4000.0}})

    real_client = httpx.AsyncClient

    def fake_client(*_a, **kw):
        return real_client(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    monkeypatch.setattr(settings, "coingecko_api_key", "cg-demo-abc123")
    assert await oracle_mod._coingecko_source("ethereum") == Decimal("4000.0")
    assert seen[-1].headers.get("x-cg-demo-api-key") == "cg-demo-abc123"
    assert "cg-demo-abc123" not in str(seen[-1].url), "a key in the URL lands in access logs"

    monkeypatch.setattr(settings, "coingecko_api_key", None)
    assert await oracle_mod._coingecko_source("ethereum") == Decimal("4000.0")
    assert "x-cg-demo-api-key" not in seen[-1].headers


# ── the source chain ──────────────────────────────────────────────────────
#
# CoinGecko rate-limited us on production and every 429 became a failed checkout. The fix
# is a second live source rather than a longer cache: a stale price on a rising market
# sells the proxy below what it costs us, which is worse than making the buyer retry.


async def test_the_second_source_covers_for_the_first() -> None:
    async def dead(_cg: str) -> Decimal:
        raise RuntimeError("429 Too Many Requests")

    async def alive(_cg: str) -> Decimal:
        return Decimal("80000")

    oracle = PriceOracle(source=dead, fallback=alive)
    assert await oracle.usd_price(get_spec("BTC", "native")) == Decimal("80000")


async def test_a_source_that_answers_with_junk_is_treated_as_down() -> None:
    """Zero is not a price. Quoting against it divides an order into infinity."""
    async def zero(_cg: str) -> Decimal:
        return Decimal("0")

    async def alive(_cg: str) -> Decimal:
        return Decimal("80000")

    oracle = PriceOracle(source=zero, fallback=alive)
    assert await oracle.usd_price(get_spec("BTC", "native")) == Decimal("80000")


async def test_a_price_from_the_last_minute_is_served_when_both_sources_die() -> None:
    state = {"up": True}

    async def flaky(_cg: str) -> Decimal:
        if not state["up"]:
            raise RuntimeError("down")
        return Decimal("80000")

    async def also_dead(_cg: str) -> Decimal:
        raise RuntimeError("down too")

    # ttl 0 so the second call always tries the network instead of reading its own cache.
    oracle = PriceOracle(source=flaky, fallback=also_dead, ttl_seconds=0)
    assert await oracle.usd_price(get_spec("BTC", "native")) == Decimal("80000")

    state["up"] = False
    assert await oracle.usd_price(get_spec("BTC", "native")) == Decimal("80000")


async def test_a_price_older_than_the_grace_window_is_not_served_at_all() -> None:
    """The whole point of the one-minute bound.

    Fifteen minutes of BTC is real money on an order priced to the cent, so past the window
    the honest answer is "ask again", not a quote we know is behind the market.

    The stored timestamp is moved back rather than the window shrunk to zero: a zero window
    passes for the wrong reason (two calls can land inside the same clock tick, and nothing
    is then older than "now"), and it would not exercise the real constant.
    """
    state = {"up": True}

    async def flaky(_cg: str) -> Decimal:
        if not state["up"]:
            raise RuntimeError("down")
        return Decimal("80000")

    async def also_dead(_cg: str) -> Decimal:
        raise RuntimeError("down too")

    oracle = PriceOracle(source=flaky, fallback=also_dead, ttl_seconds=0)
    assert await oracle.usd_price(get_spec("BTC", "native")) == Decimal("80000")

    at, price = oracle._last_good["bitcoin"]
    oracle._last_good["bitcoin"] = (at - (STALE_GRACE_SECONDS + 1), price)

    state["up"] = False
    with pytest.raises(PriceUnavailable):
        await oracle.usd_price(get_spec("BTC", "native"))


async def test_an_unpriceable_asset_is_a_503_and_says_nothing_about_our_vendors() -> None:
    """This used to escape as a raw httpx error and reach the buyer as "status 500".

    Two things are being pinned. It is a domain error, so the API renders it as a 503 with
    an envelope instead of an unhandled crash; and the text the buyer sees names no vendor
    — which source is down is our business, and the failure detail stays for the log.
    """
    async def dead(_cg: str) -> Decimal:
        raise RuntimeError("coingecko says 429")

    oracle = PriceOracle(source=dead, fallback=None)
    with pytest.raises(PriceUnavailable) as caught:
        await oracle.usd_price(get_spec("BTC", "native"))

    exc = caught.value
    assert exc.status == 503
    assert "coingecko" in exc.detail, "the log needs to know which source failed"
    assert "coingecko" not in exc.message.lower()
    assert "429" not in exc.message


# ── reading Kraken ────────────────────────────────────────────────────────


def _kraken_client(monkeypatch, payload, status=200):
    """Point httpx at a canned response.

    `real` has to come from the module rather than from `httpx.AsyncClient`: calling this
    twice in one test would otherwise capture the stub installed by the first call and
    hand it a second `transport`.
    """
    import httpx
    from httpx._client import AsyncClient as real

    def fake(*_a, **kw):
        kw.pop("transport", None)
        return real(
            transport=httpx.MockTransport(lambda _r: httpx.Response(status, json=payload)),
            **kw,
        )

    monkeypatch.setattr(httpx, "AsyncClient", fake)


async def test_kraken_price_is_read_without_knowing_their_name_for_the_pair(
    monkeypatch,
) -> None:
    """Kraken answers XBTUSD as "XXBTZUSD" but SOLUSD as "SOLUSD".

    We ask about one pair, so we take the one entry that comes back rather than keeping a
    table of their internal asset codes in step with theirs.
    """
    from app.services.payments.onchain.oracle import _kraken_source

    _kraken_client(monkeypatch, {"error": [], "result": {"XXBTZUSD": {"c": ["80702.20", "1"]}}})
    assert await _kraken_source("bitcoin") == Decimal("80702.20")

    _kraken_client(monkeypatch, {"error": [], "result": {"SOLUSD": {"c": ["101.94", "1"]}}})
    assert await _kraken_source("solana") == Decimal("101.94")


async def test_kraken_reports_failure_inside_a_200_and_we_must_notice(monkeypatch) -> None:
    """Their errors ride in the body, so raise_for_status alone would accept a failure."""
    from app.services.payments.onchain.oracle import _kraken_source

    _kraken_client(monkeypatch, {"error": ["EQuery:Unknown asset pair"], "result": {}})
    with pytest.raises(PriceUnavailable):
        await _kraken_source("bitcoin")


async def test_every_asset_we_sell_has_a_kraken_pair() -> None:
    """A fallback that covers four of five assets is not a fallback for the fifth."""
    from app.services.payments.onchain.assets import COINGECKO_IDS
    from app.services.payments.onchain.oracle import _KRAKEN_PAIRS

    missing = sorted(set(COINGECKO_IDS.values()) - set(_KRAKEN_PAIRS))
    assert not missing, f"no kraken pair mapped for: {missing}"

"""Regression: a transfer must not fall into a span the watcher never scans again.

Found in production on 2026-08-05. Two real Tron payments landed on the receiving wallet
and the watcher reported ``{'tron': 0}`` forever. Root cause: the scan window ends at the
chain tip while the query asked TronGrid for ``only_confirmed=true`` results, which lag
the tip by ~57s. The window therefore only ever covered transactions too young to be
confirmed; the cursor then advanced past them and nothing looked at that span again.

Two guarantees are locked in here:
  1. the Tron client does not filter to solidified transactions;
  2. the tick re-scans a trailing window, so a transfer the API indexed late is still
     picked up on a later pass.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.payments.onchain import load_config, run_chain_tick
from app.services.payments.onchain.clients import chain_rescan_overlap
from app.services.payments.onchain.clients.tron import TronClient

ADDR = "TWatchedAddr11111111111111111111111"


class RecordingHttp:
    """Captures the query params the client sends, returns nothing."""

    def __init__(self) -> None:
        self.get_params: list[dict[str, Any]] = []

    async def get(self, url: str, *, params: dict | None = None, headers: dict | None = None):
        self.get_params.append(dict(params or {}))
        return {"data": [], "meta": {}}

    async def post(self, url: str, *, json: Any | None = None, headers: dict | None = None):
        return {"block_header": {"raw_data": {"number": 1000, "timestamp": 1_700_000_000_000}}}

    async def aclose(self) -> None:
        return None


def _cfg():
    return load_config(
        json.dumps([{"asset": "USDT", "network": "trc20", "address": ADDR}]), "{}"
    )


async def test_tron_scan_does_not_ask_only_for_solidified_transactions() -> None:
    """only_confirmed=true made every payment invisible — it must stay gone."""
    http = RecordingHttp()
    client = TronClient(endpoint="https://x", http=http)
    await client.scan(
        from_block=0, to_block=1_700_000_000_000, methods=_cfg().methods_for_chain("tron")
    )
    assert http.get_params, "the client should have queried at least once"
    for params in http.get_params:
        assert "only_confirmed" not in params, (
            "only_confirmed filters to solidified transactions, which the tip-anchored "
            "scan window can never contain — this is the bug that lost real payments"
        )
        assert params.get("only_to") == "true"  # the address filter must stay


async def test_every_watched_chain_rescans_a_trailing_window() -> None:
    """A forward-only cursor turns any indexing lag into a permanently lost payment."""
    for chain in ("tron", "ethereum", "bsc", "bitcoin", "litecoin", "solana"):
        assert chain_rescan_overlap(chain) > 0, f"{chain} would lose late-indexed transfers"
    # Tron's overlap must clear its ~57s solidity lag with room to spare.
    assert chain_rescan_overlap("tron") >= 120_000


async def test_tick_starts_behind_the_cursor(session) -> None:
    """The scanned window must reach back before the cursor, not start at it."""
    http = RecordingHttp()
    client = TronClient(endpoint="https://x", http=http)
    cfg = _cfg()

    first = await run_chain_tick(session, client, config=cfg)
    second = await run_chain_tick(session, client, config=cfg)

    overlap = chain_rescan_overlap("tron")
    assert second.from_block <= first.to_block - overlap + 1, (
        "the second pass must re-cover the tail of the first one"
    )

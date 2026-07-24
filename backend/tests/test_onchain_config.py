"""Unit tests for on-chain config parsing (no DB)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from app.services.payments.onchain.config import OnchainConfigError, load_config


def test_parse_methods_and_rpc() -> None:
    cfg = load_config(
        json.dumps(
            [
                {
                    "asset": "USDT",
                    "network": "trc20",
                    "address": "TX",
                    "confirmations": 21,
                    "tolerance_pct": "0.5",
                    "min_amount_usd": "1",
                }
            ]
        ),
        json.dumps({"tron": {"url": "u", "api_key": "k"}, "solana": "https://sol"}),
    )
    m = cfg.require_method("USDT", "trc20")
    assert m.address == "TX"
    assert m.confirmations == 21
    assert m.tolerance_pct == Decimal("0.5")
    assert m.min_amount_usd == Decimal("1")
    assert m.chain == "tron"
    assert cfg.rpc.endpoint("tron") == "u"
    assert cfg.rpc.api_key("tron") == "k"
    assert cfg.rpc.endpoint("solana") == "https://sol"  # string form
    assert cfg.chains_in_use() == {"tron"}
    assert cfg.default_method() is not None
    assert cfg.default_method().asset == "USDT"


def test_default_confirmations_per_chain() -> None:
    cfg = load_config(json.dumps([{"asset": "USDT", "network": "erc20", "address": "0x"}]), "{}")
    assert cfg.require_method("USDT", "erc20").confirmations == 12  # ethereum default


def test_empty_config_has_no_methods() -> None:
    cfg = load_config(None, None)
    assert cfg.enabled_methods() == []
    assert cfg.default_method() is None
    assert cfg.method("USDT", "trc20") is None


def test_unsupported_rail_rejected() -> None:
    with pytest.raises(OnchainConfigError):
        load_config(json.dumps([{"asset": "DOGE", "network": "native", "address": "x"}]), "{}")


def test_missing_address_rejected() -> None:
    with pytest.raises(OnchainConfigError):
        load_config(json.dumps([{"asset": "USDT", "network": "trc20"}]), "{}")


def test_require_method_raises_for_unknown() -> None:
    cfg = load_config(json.dumps([{"asset": "USDT", "network": "trc20", "address": "TX"}]), "{}")
    with pytest.raises(OnchainConfigError):
        cfg.require_method("BTC", "native")

"""Unit tests for on-chain config parsing (no DB)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from app.services.payments.onchain.clients import build_client
from app.services.payments.onchain.config import OnchainConfigError, load_config


def test_testnet_contract_override_and_network() -> None:
    # On testnet the token contract differs from the mainnet default → overridable per rail.
    cfg = load_config(
        json.dumps(
            [{"asset": "USDT", "network": "trc20", "address": "TX",
              "token_contract": "TTestnetUSDTxxxxxxxxxxxxxxxxxxxxxx", "decimals": 6}]
        ),
        "{}",
        network="testnet",
    )
    assert cfg.network == "testnet"
    m = cfg.require_method("USDT", "trc20")
    assert m.spec.token_contract == "TTestnetUSDTxxxxxxxxxxxxxxxxxxxxxx"


def test_testnet_rejects_unoverridden_mainnet_contract() -> None:
    """A token rail left on its mainnet contract while ONCHAIN_NETWORK=testnet must fail.

    That contract does not exist on the test chain, so the watcher would scan forever and
    find nothing — indistinguishable from "no one has paid yet". Loud beats silent.
    """
    methods = json.dumps([{"asset": "USDT", "network": "trc20", "address": "TX"}])
    load_config(methods, "{}", network="mainnet")  # fine on mainnet
    with pytest.raises(OnchainConfigError, match="MAINNET token_contract"):
        load_config(methods, "{}", network="testnet")


def test_mainnet_rejects_a_testnet_confirmation_threshold() -> None:
    """The mirror of the guard above: a low confirmation count must not reach mainnet.

    On testnet BTC runs at 1 confirmation so a test payment takes ten minutes instead of
    an hour. ONCHAIN_METHODS is one JSON blob that gets duplicated and has its addresses
    swapped for the real wallets — the confirmation counts are what nobody re-reads while
    doing that, and a deposit finalised at one confirmation can be reorged away after the
    proxy is already issued.

    The check is ``strict``-gated so it applies to a deployed config and not to the unit
    tests that drive rails at two or three confirmations on purpose; get_onchain_config
    sets that flag, and it is the only path the running app takes.
    """
    weak = json.dumps([{"asset": "BTC", "network": "native", "address": "tb1x",
                        "confirmations": 1}])
    load_config(weak, "{}", network="testnet", strict=True)  # fine on a test chain
    with pytest.raises(OnchainConfigError, match="requires at least 6"):
        load_config(weak, "{}", network="mainnet", strict=True)

    # Dropping the key is the fix the message asks for: the chain default applies.
    plain = json.dumps([{"asset": "BTC", "network": "native", "address": "bc1x"}])
    assert load_config(plain, "{}", network="mainnet", strict=True).require_method(
        "BTC", "native"
    ).confirmations == 6

    # Waiting longer than the default is a safe direction and stays allowed.
    careful = json.dumps([{"asset": "BTC", "network": "native", "address": "bc1x",
                           "confirmations": 12}])
    assert load_config(careful, "{}", network="mainnet", strict=True).require_method(
        "BTC", "native"
    ).confirmations == 12

    # And the same weak config passes when a test builds it, which is the whole point of
    # the flag — otherwise eleven on-chain test modules would have to fake long chains.
    load_config(weak, "{}", network="mainnet")


def test_testnet_allows_native_rails_without_override() -> None:
    """Native coins have no contract, so there is nothing to override — must not fail."""
    cfg = load_config(
        json.dumps(
            [
                {"asset": "BTC", "network": "native", "address": "tb1qxyz"},
                {"asset": "ETH", "network": "native", "address": "0xabc"},
                {"asset": "SOL", "network": "native", "address": "So1x"},
            ]
        ),
        "{}",
        network="testnet",
    )
    assert len(cfg.enabled_methods()) == 3


def test_testnet_rejects_unoverridden_spl_mint() -> None:
    """Same guard on the Solana side, where the field is token_mint rather than a contract."""
    with pytest.raises(OnchainConfigError, match="MAINNET token_mint"):
        load_config(
            json.dumps([{"asset": "USDC", "network": "spl", "address": "So1x"}]),
            "{}",
            network="testnet",
        )


def test_factory_uses_testnet_defaults() -> None:
    """ONCHAIN_NETWORK must pick a different default endpoint, and neither may be empty."""
    from app.services.payments.onchain.clients.factory import _default_endpoint

    # Verified on-chain 2026-07-31: symbol()="USDC", decimals()=6 on Sepolia.
    sepolia_usdc = "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238"
    mainnet_methods = json.dumps([{"asset": "USDC", "network": "erc20", "address": "0xabc"}])
    testnet_methods = json.dumps(
        [{"asset": "USDC", "network": "erc20", "address": "0xabc",
          "token_contract": sepolia_usdc, "decimals": 6}]
    )
    assert build_client("ethereum", load_config(mainnet_methods, "{}", network="mainnet")) is not None
    assert build_client("ethereum", load_config(testnet_methods, "{}", network="testnet")) is not None
    mainnet_url = _default_endpoint("ethereum", "mainnet")
    testnet_url = _default_endpoint("ethereum", "testnet")
    assert mainnet_url and testnet_url and mainnet_url != testnet_url
    assert "sepolia" in (testnet_url or "")


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

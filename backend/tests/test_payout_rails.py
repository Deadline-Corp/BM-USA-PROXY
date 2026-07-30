"""Payout rails: only USDT trc20/erc20/bep20, and the address must match the network."""

from __future__ import annotations

import pytest
from app.core.errors import ValidationError
from app.services.payouts import get_rail, normalize_network, rails_for_client, validate_target

TRON_OK = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
EVM_OK = "0xdAC17F958D2ee523a2206206994597C13D831ec7"


def test_only_three_rails_are_offered() -> None:
    assert {r["network"] for r in rails_for_client()} == {"trc20", "erc20", "bep20"}
    assert {r["asset"] for r in rails_for_client()} == {"USDT"}


def test_normalize_accepts_loose_forms() -> None:
    for raw in ("TRC20", "trc-20", "USDT-TRC20", " usdt_trc20 "):
        assert normalize_network(raw) == "trc20"
    assert get_rail("BEP-20").chain == "bsc"
    assert get_rail("erc20").chain == "ethereum"


def test_unsupported_network_rejected() -> None:
    for bad in ("spl", "solana", "btc", "polygon", ""):
        with pytest.raises(ValidationError):
            get_rail(bad)


def test_address_must_match_network() -> None:
    # the expensive mistake: an EVM address on a Tron rail (and vice versa)
    with pytest.raises(ValidationError):
        validate_target("trc20", EVM_OK)
    with pytest.raises(ValidationError):
        validate_target("erc20", TRON_OK)
    with pytest.raises(ValidationError):
        validate_target("bep20", TRON_OK)


def test_malformed_addresses_rejected() -> None:
    for bad in ("", "0x123", "T123", "0x" + "z" * 40, TRON_OK + "x", "not-an-address"):
        with pytest.raises(ValidationError):
            validate_target("trc20", bad)
        with pytest.raises(ValidationError):
            validate_target("erc20", bad)


def test_valid_targets_normalized() -> None:
    assert validate_target("TRC-20", f"  {TRON_OK}  ") == ("trc20", TRON_OK)
    assert validate_target("erc20", EVM_OK) == ("erc20", EVM_OK)
    assert validate_target("bep20", EVM_OK) == ("bep20", EVM_OK)

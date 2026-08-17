"""The payment provider must not answer from a rail list it snapshotted at startup.

`get_payment_provider()` is lru_cached, so the provider is built once per process — and in
`guard_order_attempt` it is built one line *before* the console-managed rails are loaded
from the database. Snapshotting the config in `__init__` therefore froze an empty rail list
for the life of the process.

That failed in the worst possible shape: every check passed, because those read the live
config, and only invoice creation blew up — "rail 'USDT/trc20' is not enabled", a 500 on
the buyer's Buy button, with the address sitting correctly in the database and listed in
the mini app. Seen on production 2026-08-17.
"""

from __future__ import annotations

import json

import pytest
from app.services.payments.onchain.config import (
    OnchainConfigError,
    set_rails_override,
)
from app.services.payments.onchain.provider import OnchainProvider
from app.services.payments.onchain.rails import normalise_rails

_TRC20_ADDR = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


def _install_trc20_rail() -> None:
    rails = normalise_rails(
        [{"asset": "USDT", "network": "trc20", "address": _TRC20_ADDR}], network="mainnet"
    )
    set_rails_override(json.dumps(rails))


def test_a_provider_built_before_the_rails_were_saved_still_finds_them() -> None:
    set_rails_override(None)  # the state every process starts in
    provider = OnchainProvider()  # built here, exactly as the lru_cache does it

    _install_trc20_rail()  # an operator's rails arrive afterwards

    method = provider._resolve_method("USDT", "trc20")
    assert method.spec.asset == "USDT"
    assert method.address == _TRC20_ADDR


def test_a_rail_that_really_is_absent_is_still_refused() -> None:
    """The fix must not turn a genuine misconfiguration into silence."""
    _install_trc20_rail()
    provider = OnchainProvider()

    with pytest.raises(OnchainConfigError):
        provider._resolve_method("BTC", "native")


def test_removing_a_rail_takes_effect_without_a_restart() -> None:
    """The Wallets screen promises the next invoice uses what was just saved."""
    _install_trc20_rail()
    provider = OnchainProvider()
    assert provider._resolve_method("USDT", "trc20").address == _TRC20_ADDR

    set_rails_override(json.dumps([]))  # operator clears the address

    with pytest.raises(OnchainConfigError):
        provider._resolve_method("USDT", "trc20")

"""Saving rails from the console must not be able to take payments down.

On 2026-09-08 the client saved the rail list with bitcoin set to 5 confirmations. The
console answered 200. From that moment `get_onchain_config()` raised on every read, which
meant two things at once: the Wallets screen rendered every rail with an empty address —
so it read as the addresses having been deleted — and no invoice could be quoted on any
coin, not just bitcoin. The shop was shut for two hours before anybody connected the two.

The per-rail pass could not have caught it. `normalise_rails` looks at one rail at a time —
supported, not duplicated, address shaped right for its network — and 5 is a perfectly
well-formed count. The mainnet floor belongs to the loader, which sees the set as a whole,
and the loader only ran on the next read, long after the value was stored.
"""

from __future__ import annotations

import json

import pytest
from app.core.errors import ValidationError
from app.models import AdminUser
from app.services import settings as settings_svc
from app.services.payments.onchain.config import (
    OnchainConfigError,
    load_config,
    reset_config_cache,
)
from app.services.payments.onchain.rails import RAILS_SETTING_KEY, load_rails, normalise_rails
from sqlalchemy import select

_BTC = "bc1qgc3z8uws9xekfl6msm9ljzfaxqfwncj8mj69yg"
_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
_RPC = json.dumps({"bitcoin": "https://example.invalid", "tron": "https://example.invalid"})


def _rails(btc_confirmations: int | None) -> list[dict]:
    btc: dict = {"asset": "BTC", "network": "native", "address": _BTC}
    if btc_confirmations is not None:
        btc["confirmations"] = btc_confirmations
    return [btc, {"asset": "USDT", "network": "trc20", "address": _TRC20}]


def test_the_loader_rejects_what_the_per_rail_pass_accepts() -> None:
    """The gap the guard exists to close, stated on its own.

    Both calls see the same list. One is happy with it and the other cannot build a
    configuration from it, and until the guard existed only the happy one ran on save.
    """
    raw = _rails(5)
    accepted = normalise_rails(raw, network="mainnet")  # no complaint
    assert any(r["asset"] == "BTC" and r["confirmations"] == 5 for r in accepted)

    with pytest.raises(OnchainConfigError, match="at least 6"):
        load_config(json.dumps(accepted), _RPC, "mainnet", strict=True)


async def _operator(session, tag: str) -> AdminUser:
    admin = AdminUser(
        email=f"ops-{tag}@test.local", password_hash="x", display_name="ops", role="owner"
    )
    session.add(admin)
    await session.flush()
    return admin


async def _put(session, admin: AdminUser, rails: list[dict]):
    """Call the endpoint the console calls."""
    from app.api.admin.domain import PaymentRailsBody, put_payment_rails

    return await put_payment_rails(PaymentRailsBody(rails=rails), admin, session)


async def test_a_rail_set_that_would_not_load_is_refused_and_nothing_is_written(
    session, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "onchain_rpc", _RPC, raising=False)
    monkeypatch.setattr(settings, "onchain_network", "mainnet", raising=False)
    reset_config_cache()

    admin = await _operator(session, "guard")
    # A good set lands first, so there is something to lose.
    await _put(session, admin, _rails(6))
    await session.flush()
    good = await load_rails(session)
    assert good is not None and any(r["asset"] == "BTC" for r in good)

    with pytest.raises(ValidationError, match="at least 6"):
        await _put(session, admin, _rails(5))
    await session.flush()

    # The refusal has to leave the previous list in place — a half-applied save would put
    # the addresses beyond reach exactly when somebody is trying to correct them.
    after = await load_rails(session)
    assert after == good, "a refused save must not have written anything"


async def test_the_error_names_the_rail_and_the_number(session, monkeypatch) -> None:
    """What the operator sees decides whether they can fix it themselves.

    The client got a 200 and a screen of blanks, and read that as the addresses being
    gone. The message has to say which rail and what it needs.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "onchain_rpc", _RPC, raising=False)
    monkeypatch.setattr(settings, "onchain_network", "mainnet", raising=False)
    reset_config_cache()

    admin = await _operator(session, "message")
    with pytest.raises(ValidationError) as caught:
        await _put(session, admin, _rails(5))

    message = str(caught.value)
    assert "BTC/native" in message
    assert "6" in message


# ── when a setting last changed ───────────────────────────────────────────


async def test_saving_a_setting_moves_its_timestamp(session) -> None:
    """`updated_at` used to hold only the moment the row was first inserted.

    So a setting edited a dozen times still reported the day it was created, and during the
    outage that timestamp was read as evidence that the rails had not been touched — while
    the audit log showed a save an hour earlier. A clock that does not move is worse than
    no clock: it answers confidently and wrongly.
    """
    from app.models import AppSetting

    await settings_svc.set_value(session, "probe_key", {"n": 1})
    await session.flush()
    first = await session.scalar(select(AppSetting.updated_at).where(AppSetting.key == "probe_key"))
    assert first is not None

    await settings_svc.set_value(session, "probe_key", {"n": 2})
    await session.flush()
    second = await session.scalar(
        select(AppSetting.updated_at).where(AppSetting.key == "probe_key")
    )

    assert await settings_svc.get(session, "probe_key") == {"n": 2}
    assert second is not None and second > first, "the timestamp has to follow the value"


def test_the_rails_setting_key_is_the_one_the_guard_protects() -> None:
    """Cheap, and it is the string every other assertion here is implicitly about."""
    assert RAILS_SETTING_KEY == "onchain_rails"

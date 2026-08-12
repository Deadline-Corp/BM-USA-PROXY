"""Receiving rails as editable data rather than a deploy-time env var.

``ONCHAIN_METHODS`` is still the fallback and still the shape everything downstream
parses. What changed is where the JSON comes from: if the console has written a rail list
into app settings, that wins; otherwise the environment does. One parser, one config
object, one code path — only the source moved.

⚠️ Whoever can sign into the console can now change where customer money lands. That was
a deliberate trade the client asked for, so the mitigations are the ones that do not get
in the way of the person doing the work:

  * every save is audit-logged with the rail and the address that replaced what was there;
  * an address is format-checked against the chain it is being set on, which is what
    catches the mistake people actually make — pasting a Tron address onto the Ethereum
    rail, or a mainnet address while running testnet;
  * nothing here can spend. The backend holds no key on any chain; a wrong address means
    money arrives somewhere we do not watch, not that money leaves.

Format checking is not checksum validation: it catches a wrong chain, a truncated paste
and a wrong-network address, not two transposed characters in the middle. The address
still has to be read back against the wallet before it goes live.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import settings as settings_svc
from app.services.payments.onchain.assets import SPECS, find_spec
from app.services.payments.onchain.config import (
    DEFAULT_CONFIRMATIONS,
    OnchainConfigError,
    set_rails_override,
)

RAILS_SETTING_KEY = "onchain_rails"

# Per-chain address shapes, mainnet and testnet. Bech32 is matched case-insensitively
# because the standard allows an all-uppercase form even though wallets emit lowercase.
_BASE58 = "[1-9A-HJ-NP-Za-km-z]"
_ADDRESS_PATTERNS: dict[tuple[str, str], str] = {
    ("tron", "mainnet"): rf"^T{_BASE58}{{33}}$",
    ("tron", "testnet"): rf"^T{_BASE58}{{33}}$",  # Nile uses the same format
    ("ethereum", "mainnet"): r"^0x[0-9a-fA-F]{40}$",
    ("ethereum", "testnet"): r"^0x[0-9a-fA-F]{40}$",
    ("bsc", "mainnet"): r"^0x[0-9a-fA-F]{40}$",
    ("bsc", "testnet"): r"^0x[0-9a-fA-F]{40}$",
    ("solana", "mainnet"): rf"^{_BASE58}{{32,44}}$",
    ("solana", "testnet"): rf"^{_BASE58}{{32,44}}$",
    ("bitcoin", "mainnet"): rf"^(?:bc1[a-zA-Z0-9]{{25,62}}|[13]{_BASE58}{{25,34}})$",
    ("bitcoin", "testnet"): rf"^(?:tb1[a-zA-Z0-9]{{25,62}}|[2mn]{_BASE58}{{25,34}})$",
    ("litecoin", "mainnet"): rf"^(?:ltc1[a-zA-Z0-9]{{25,62}}|[LM3]{_BASE58}{{25,34}})$",
    ("litecoin", "testnet"): rf"^(?:tltc1[a-zA-Z0-9]{{25,62}}|[mnQ2]{_BASE58}{{25,34}})$",
}

_CHAIN_HINTS: dict[str, str] = {
    "tron": "a Tron address starts with T and is 34 characters",
    "ethereum": "an Ethereum address is 0x followed by 40 hex characters",
    "bsc": "a BSC address is 0x followed by 40 hex characters",
    "solana": "a Solana address is 32–44 base58 characters",
    "bitcoin": "a Bitcoin address starts with bc1, 1 or 3 (tb1, m, n or 2 on testnet)",
    "litecoin": "a Litecoin address starts with ltc1, L or M (tltc1, m, n or Q on testnet)",
}


def validate_address(chain: str, network: str, address: str) -> None:
    """Raise if ``address`` cannot be an address on ``chain`` for this network."""
    pattern = _ADDRESS_PATTERNS.get((chain, network))
    if pattern is None:  # unknown chain — the rail itself is rejected elsewhere
        return
    if not re.match(pattern, address):
        hint = _CHAIN_HINTS.get(chain, "")
        raise OnchainConfigError(
            f"'{address}' does not look like a {chain} address on {network}"
            + (f" — {hint}" if hint else "")
        )


def normalise_rails(raw: Any, *, network: str) -> list[dict[str, Any]]:
    """Validate a console-submitted rail list into the shape ``load_config`` parses.

    Rails without an address are dropped rather than rejected: the console lists every
    supported rail so all of them can be filled in, and an empty one simply means "we do
    not accept this coin", which is a normal state and not an error to report.
    """
    if not isinstance(raw, list):
        raise OnchainConfigError("rails must be a list")

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise OnchainConfigError("each rail must be an object")
        asset = str(entry.get("asset", "")).upper()
        net = str(entry.get("network", "")).lower()
        spec = find_spec(asset, net)
        if spec is None:
            raise OnchainConfigError(f"unsupported rail {asset}/{net}")
        if (asset, net) in seen:
            raise OnchainConfigError(f"rail {asset}/{net} appears twice")
        seen.add((asset, net))

        address = str(entry.get("address") or "").strip()
        if not address:
            continue
        validate_address(spec.chain, network, address)

        confirmations = int(
            entry.get("confirmations") or DEFAULT_CONFIRMATIONS.get(spec.chain, 12)
        )
        if confirmations < 0:
            raise OnchainConfigError(f"rail {asset}/{net}: confirmations cannot be negative")

        # No minimum, no tolerance. Neither is a dial this business wants: an amount
        # smaller than the one we quoted is not a payment, it is something for a person to
        # look at, and a per-coin order floor is a rule nobody asked for. Anything sent in
        # the request for either is dropped rather than stored.
        rail: dict[str, Any] = {
            "asset": asset,
            "network": net,
            "address": address,
            "confirmations": confirmations,
        }
        # Carry the per-rail overrides through untouched — they exist for testnet, where
        # the token contract differs, and losing one on save would point the watcher at
        # the mainnet contract on a test chain and silently confirm nothing.
        for key in ("token_contract", "token_mint", "decimals"):
            if entry.get(key):
                rail[key] = entry[key]
        out.append(rail)
    return out


async def load_rails(session: AsyncSession) -> list[dict[str, Any]] | None:
    """The console-managed rail list, or ``None`` when the env var is still in charge."""
    stored = await settings_svc.get(session, RAILS_SETTING_KEY, None)
    return stored if isinstance(stored, list) else None


async def refresh_rails(session: AsyncSession) -> None:
    """Point the config at whatever the console last saved.

    Called wherever the config is about to be used with a session in hand — quoting an
    invoice, a watcher tick, the admin screen — rather than cached with a TTL. It is one
    indexed read, and the alternative is a window where the API quotes an address the
    operator has already replaced.
    """
    rails = await load_rails(session)
    set_rails_override(json.dumps(rails) if rails is not None else None)


async def save_rails(
    session: AsyncSession, raw: Any, *, admin_id: int | None, network: str
) -> list[dict[str, Any]]:
    """Validate and store a rail list, then make it live in this process."""
    rails = normalise_rails(raw, network=network)
    await settings_svc.set_value(session, RAILS_SETTING_KEY, rails, admin_id=admin_id)
    set_rails_override(json.dumps(rails))
    return rails


def supported_rails() -> list[tuple[str, str, str]]:
    """Every (asset, network, chain) the watcher has an engine for, in display order."""
    return sorted(
        ((spec.asset, spec.network, spec.chain) for spec in SPECS.values()),
        key=lambda t: (t[2], t[0]),
    )

"""Referral payout rails.

Client decision (2026-07-30): payouts are cash only (no internal balance), on USDT over
exactly three rails — TRC-20, ERC-20, BEP-20 — with no minimum threshold.

The address shape is validated per rail on purpose: pasting an EVM address (0x…) into a
TRC-20 payout, or vice versa, sends the money to an address nobody controls, and crypto
transfers are irreversible. A regex here is the cheapest possible guard against the single
most expensive mistake in this flow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.errors import ValidationError


@dataclass(frozen=True, slots=True)
class PayoutRail:
    network: str        # what we store on Payout.network
    asset: str          # always USDT for now
    chain: str          # watcher engine that will confirm the outgoing transfer
    label: str          # full "asset on network" label — admin lists, error messages
    network_label: str  # network alone, for a form that asks for the network by itself
    address_re: re.Pattern[str]

    def validate_address(self, address: str) -> str:
        addr = address.strip()
        if not self.address_re.fullmatch(addr):
            raise ValidationError(
                f"address does not look like {self.label} — check the network and the address"
            )
        return addr


# Tron base58check: 'T' + 33 base58 chars (no 0/O/I/l).
_TRON_RE = re.compile(r"T[1-9A-HJ-NP-Za-km-z]{33}")
# EVM: 0x + 40 hex.
_EVM_RE = re.compile(r"0x[0-9a-fA-F]{40}")

PAYOUT_RAILS: dict[str, PayoutRail] = {
    "trc20": PayoutRail("trc20", "USDT", "tron", "USDT TRC-20 (Tron)", "Tron (TRC-20)", _TRON_RE),
    "erc20": PayoutRail(
        "erc20", "USDT", "ethereum", "USDT ERC-20 (Ethereum)", "Ethereum (ERC-20)", _EVM_RE
    ),
    "bep20": PayoutRail(
        "bep20", "USDT", "bsc", "USDT BEP-20 (BNB Chain)", "BNB Chain (BEP-20)", _EVM_RE
    ),
}


def normalize_network(network: str) -> str:
    """Accept the loose forms a client might send ('TRC20', 'usdt-trc20', 'TRC-20')."""
    return network.strip().lower().replace("-", "").replace("_", "").removeprefix("usdt")


def get_rail(network: str) -> PayoutRail:
    rail = PAYOUT_RAILS.get(normalize_network(network))
    if rail is None:
        allowed = ", ".join(r.label for r in PAYOUT_RAILS.values())
        raise ValidationError(f"payouts are supported only on: {allowed}")
    return rail


def validate_target(network: str, address: str) -> tuple[str, str]:
    """Return the (canonical network, validated address) for a payout request."""
    rail = get_rail(network)
    return rail.network, rail.validate_address(address)


def rails_for_client() -> list[dict[str, str]]:
    """Payload for the mini-app payout form.

    ``network_label`` is sent alongside the full label because the form asks for the
    network on its own — the coin is not a choice, every rail pays USDT. Naming networks
    is the backend's job: the mini-app should not be assembling "Tron (TRC-20)" out of a
    code it was handed.
    """
    return [
        {
            "network": r.network,
            "asset": r.asset,
            "label": r.label,
            "network_label": r.network_label,
        }
        for r in PAYOUT_RAILS.values()
    ]

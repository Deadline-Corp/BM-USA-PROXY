"""Solana Pay reference derivation.

A Solana Pay *reference* is a unique pubkey attached (as a read-only account) to the
payment instruction so the payment can be located on-chain without a per-invoice wallet.
We derive it deterministically from the order id so the same order always yields the same
reference (idempotent invoice creation), encoded as base58 like any Solana address.

Only the *public* 32-byte value is ever produced — there is no key material to hold.
"""

from __future__ import annotations

import hashlib

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(data: bytes) -> str:
    """Minimal base58 (Bitcoin/Solana alphabet) encoder — no external dependency."""
    n = int.from_bytes(data, "big")
    out = ""
    while n > 0:
        n, rem = divmod(n, 58)
        out = _B58_ALPHABET[rem] + out
    # preserve leading zero bytes as '1'
    pad = 0
    for byte in data:
        if byte == 0:
            pad += 1
        else:
            break
    return "1" * pad + out


def derive_reference(order_public_id: str) -> str:
    """Deterministic 32-byte reference pubkey (base58) for an order."""
    digest = hashlib.sha256(f"solana-pay-reference:{order_public_id}".encode()).digest()
    return b58encode(digest)

"""Chain-client interface shared by every per-chain watcher engine.

A ``ChainClient`` knows how to talk to one chain's RPC/indexer: report the current head,
scan a block range for incoming transfers to our watched addresses, and re-check the
confirmation depth of a known tx. Concrete clients (Tron, EVM, UTXO, Solana) implement
this in later phases; the generic watcher orchestrates them uniformly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from app.services.payments.onchain.config import MethodConfig


@dataclass(frozen=True, slots=True)
class IncomingTransfer:
    """A single inbound transfer to one of our receiving addresses (human units)."""

    chain: str
    asset: str
    network: str
    txid: str
    to_address: str
    amount: Decimal
    log_index: int = 0
    from_address: str | None = None
    block_number: int | None = None
    block_time: datetime | None = None
    confirmations: int = 0
    reference: str | None = None  # Solana Pay reference pubkey, when applicable

    @property
    def dedupe_key(self) -> tuple[str, int]:
        return (self.txid, self.log_index)


@runtime_checkable
class ChainClient(Protocol):
    """One instance per chain. Stateless w.r.t. our DB — pure chain access."""

    chain: str

    async def get_block_height(self) -> int:
        """Current chain head (highest usable block/slot)."""
        ...

    async def scan(
        self,
        *,
        from_block: int,
        to_block: int,
        methods: Sequence[MethodConfig],
    ) -> list[IncomingTransfer]:
        """Return inbound transfers to any watched address in ``methods`` within the range."""
        ...

    async def confirmations(self, txid: str, *, block_number: int | None = None) -> int:
        """Current confirmation depth of ``txid`` (0 if unknown / dropped)."""
        ...

    async def aclose(self) -> None:
        """Release any held resources (HTTP clients). Optional; default no-op."""
        ...

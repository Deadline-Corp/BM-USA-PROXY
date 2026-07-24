"""Solana chain client (native SOL + USDT/USDC SPL) over JSON-RPC.

Solana has no address+block-range log filter, so detection walks the receiving account's
signature history (``getSignaturesForAddress``) and reads each transaction's balance deltas:

* native SOL — the lamport delta of the receiving address in pre/postBalances,
* SPL tokens — the token-amount delta of the receiving **token account** (ATA) in
  pre/postTokenBalances for the configured mint.

Only ``finalized`` commitment is queried, so a detected transfer is already irreversible
(the Solana confirmations threshold is 0). Cursor = slot; matching is by amount (each
open invoice has a unique expected amount). A Solana Pay reference is derived per invoice
in P0 and remains available for future reference-based matching.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from app.services.payments.onchain.chain_client import IncomingTransfer
from app.services.payments.onchain.clients.http import HttpxJson, JsonHttp
from app.services.payments.onchain.config import MethodConfig

_LAMPORTS = Decimal(10) ** 9
_FINALIZED = "finalized"


class SolanaRpcError(RuntimeError):
    """A Solana JSON-RPC call returned an error object."""


class SolanaClient:
    def __init__(
        self,
        *,
        endpoint: str,
        http: JsonHttp | None = None,
        page_limit: int = 100,
        max_pages: int = 10,
    ) -> None:
        self.chain = "solana"
        self._endpoint = endpoint
        self._http = http or HttpxJson()
        self._page_limit = page_limit
        self._max_pages = max_pages

    async def _rpc(self, method: str, params: list) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        data = await self._http.post(self._endpoint, json=payload)
        if isinstance(data, dict) and data.get("error"):
            raise SolanaRpcError(f"{method}: {data['error']}")
        return (data or {}).get("result") if isinstance(data, dict) else None

    async def _slot(self) -> int:
        return int(await self._rpc("getSlot", [{"commitment": _FINALIZED}]))

    async def get_block_height(self) -> int:
        return await self._slot()

    async def _signatures_since(self, address: str, from_slot: int) -> list[str]:
        """Signatures for an address newer than the cursor slot (newest-first walk)."""
        out: list[str] = []
        before: str | None = None
        for _ in range(self._max_pages):
            opts: dict[str, Any] = {"limit": self._page_limit, "commitment": _FINALIZED}
            if before:
                opts["before"] = before
            sigs = await self._rpc("getSignaturesForAddress", [address, opts])
            if not sigs:
                break
            stop = False
            for entry in sigs:
                if entry.get("err"):
                    continue
                if int(entry.get("slot", 0)) < from_slot:
                    stop = True
                    break
                out.append(str(entry["signature"]))
            before = str(sigs[-1]["signature"])
            if stop or int(sigs[-1].get("slot", 0)) < from_slot:
                break
        return out

    async def scan(
        self, *, from_block: int, to_block: int, methods: Sequence[MethodConfig]
    ) -> list[IncomingTransfer]:
        head = await self._slot()
        transfers: list[IncomingTransfer] = []
        # one signature walk per watched account, then decode each tx once
        for method in methods:
            for signature in await self._signatures_since(method.address, from_block):
                tx = await self._rpc(
                    "getTransaction",
                    [
                        signature,
                        {
                            "encoding": "jsonParsed",
                            "maxSupportedTransactionVersion": 0,
                            "commitment": _FINALIZED,
                        },
                    ],
                )
                transfer = self._decode(tx, signature, method, head)
                if transfer is not None:
                    transfers.append(transfer)
        return transfers

    def _decode(
        self, tx: Any, signature: str, method: MethodConfig, head: int
    ) -> IncomingTransfer | None:
        if not tx or (tx.get("meta") or {}).get("err"):
            return None
        meta = tx.get("meta") or {}
        keys = [k.get("pubkey") for k in tx.get("transaction", {}).get("message", {}).get(
            "accountKeys", []
        )]
        slot = int(tx.get("slot", 0))
        confs = max(0, head - slot)
        spec = method.spec

        if spec.is_native:
            if method.address not in keys:
                return None
            idx = keys.index(method.address)
            delta = int(meta.get("postBalances", [])[idx]) - int(meta.get("preBalances", [])[idx])
            if delta <= 0:
                return None
            amount = Decimal(delta) / _LAMPORTS
        else:
            spl_amount = self._spl_delta(meta, keys, method)
            if spl_amount is None or spl_amount <= 0:
                return None
            amount = spl_amount

        return IncomingTransfer(
            chain=self.chain,
            asset=spec.asset,
            network=spec.network,
            txid=signature,
            to_address=method.address,
            amount=amount,
            block_number=slot,
            confirmations=confs,
        )

    @staticmethod
    def _spl_delta(meta: dict, keys: list, method: MethodConfig) -> Decimal | None:
        pre = {int(p["accountIndex"]): p for p in (meta.get("preTokenBalances") or [])}
        for post in meta.get("postTokenBalances") or []:
            account_index = int(post.get("accountIndex", -1))
            if account_index < 0 or account_index >= len(keys):
                continue
            if keys[account_index] != method.address:
                continue
            if post.get("mint") != method.spec.token_mint:
                continue
            post_amount = int(post.get("uiTokenAmount", {}).get("amount", 0))
            pre_entry = pre.get(account_index, {})
            pre_amount = int((pre_entry.get("uiTokenAmount") or {}).get("amount", 0))
            delta = post_amount - pre_amount
            if delta <= 0:
                return None
            return Decimal(delta) / (Decimal(10) ** method.spec.decimals)
        return None

    async def confirmations(self, txid: str, *, block_number: int | None = None) -> int:
        result = await self._rpc(
            "getSignatureStatuses", [[txid], {"searchTransactionHistory": True}]
        )
        value = ((result or {}).get("value") or [None])[0]
        if not value:
            return 0
        if value.get("confirmationStatus") != _FINALIZED:
            return 0
        slot = int(value.get("slot", 0))
        head = await self._slot()
        return max(0, head - slot)

    async def aclose(self) -> None:
        await self._http.aclose()

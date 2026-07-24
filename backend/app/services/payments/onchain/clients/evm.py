"""EVM chain client (Ethereum + BSC) over standard JSON-RPC.

One engine serves every EVM chain — the same code handles Ethereum (ETH, USDT/USDC-ERC20)
and BSC (USDT/USDC-BEP20); only the endpoint + token decimals differ (per AssetSpec).

Detection:
* ERC-20/BEP-20 tokens — ``eth_getLogs`` for Transfer(address,address,uint256) events
  whose ``to`` topic is our receiving address (efficient, provider-agnostic).
* native coin (ETH) — scan each block's transactions for ``to == our address`` (heavier,
  so the per-tick block window is kept small in the factory).

Cursor semantics are block numbers; confirmation depth = head − tx block + 1.
The RPC key, if any, is embedded in the endpoint URL (Infura/Alchemy style).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from app.services.payments.onchain.chain_client import IncomingTransfer
from app.services.payments.onchain.clients.http import HttpxJson, JsonHttp
from app.services.payments.onchain.config import MethodConfig

# keccak256("Transfer(address,address,uint256)")
_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class EvmRpcError(RuntimeError):
    """A JSON-RPC call returned an error object."""


def _to_int(hex_str: str | None) -> int:
    if not hex_str:
        return 0
    return int(hex_str, 16)


def _addr_topic(address: str) -> str:
    """Left-pad a 20-byte address into a 32-byte log topic (lowercased)."""
    return "0x" + address[2:].lower().rjust(64, "0")


def _topic_to_address(topic: str) -> str:
    return "0x" + topic[-40:]


class EvmClient:
    def __init__(
        self,
        *,
        chain: str,
        endpoint: str,
        http: JsonHttp | None = None,
    ) -> None:
        self.chain = chain
        self._endpoint = endpoint
        self._http = http or HttpxJson()

    async def _rpc(self, method: str, params: list) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        data = await self._http.post(self._endpoint, json=payload)
        if isinstance(data, dict) and data.get("error"):
            raise EvmRpcError(f"{method}: {data['error']}")
        return (data or {}).get("result") if isinstance(data, dict) else None

    async def _block_number(self) -> int:
        return _to_int(await self._rpc("eth_blockNumber", []))

    async def get_block_height(self) -> int:
        return await self._block_number()

    async def scan(
        self, *, from_block: int, to_block: int, methods: Sequence[MethodConfig]
    ) -> list[IncomingTransfer]:
        head = await self._block_number()
        transfers: list[IncomingTransfer] = []
        for method in methods:
            spec = method.spec
            if spec.token_contract:
                transfers += await self._scan_token(method, from_block, to_block, head)
            elif spec.is_native:
                transfers += await self._scan_native(method, from_block, to_block, head)
        return transfers

    async def _scan_token(
        self, method: MethodConfig, from_block: int, to_block: int, head: int
    ) -> list[IncomingTransfer]:
        spec = method.spec
        params = [
            {
                "fromBlock": hex(from_block),
                "toBlock": hex(to_block),
                "address": spec.token_contract,
                "topics": [_TRANSFER_TOPIC, None, _addr_topic(method.address)],
            }
        ]
        logs = await self._rpc("eth_getLogs", params)
        out: list[IncomingTransfer] = []
        for entry in logs or []:
            block_number = _to_int(entry.get("blockNumber"))
            amount = Decimal(_to_int(entry.get("data"))) / (Decimal(10) ** spec.decimals)
            if amount <= 0:
                continue
            topics = entry.get("topics") or []
            out.append(
                IncomingTransfer(
                    chain=self.chain,
                    asset=spec.asset,
                    network=spec.network,
                    txid=str(entry.get("transactionHash")),
                    to_address=method.address,
                    amount=amount,
                    log_index=_to_int(entry.get("logIndex")),
                    from_address=_topic_to_address(topics[1]) if len(topics) > 1 else None,
                    block_number=block_number,
                    confirmations=max(1, head - block_number + 1) if block_number else 1,
                )
            )
        return out

    async def _scan_native(
        self, method: MethodConfig, from_block: int, to_block: int, head: int
    ) -> list[IncomingTransfer]:
        spec = method.spec
        target = method.address.lower()
        out: list[IncomingTransfer] = []
        for number in range(from_block, to_block + 1):
            block = await self._rpc("eth_getBlockByNumber", [hex(number), True])
            if not block:
                continue
            for tx in block.get("transactions", []):
                to_addr = tx.get("to")
                value = _to_int(tx.get("value"))
                if not to_addr or to_addr.lower() != target or value <= 0:
                    continue
                out.append(
                    IncomingTransfer(
                        chain=self.chain,
                        asset=spec.asset,
                        network=spec.network,
                        txid=str(tx.get("hash")),
                        to_address=method.address,
                        amount=Decimal(value) / (Decimal(10) ** spec.decimals),
                        from_address=tx.get("from"),
                        block_number=number,
                        confirmations=max(1, head - number + 1),
                    )
                )
        return out

    async def confirmations(self, txid: str, *, block_number: int | None = None) -> int:
        if block_number is None:
            receipt = await self._rpc("eth_getTransactionReceipt", [txid])
            if not receipt:
                return 0
            block_number = _to_int(receipt.get("blockNumber"))
        if not block_number:
            return 0
        head = await self._block_number()
        return max(0, head - block_number + 1)

    async def aclose(self) -> None:
        await self._http.aclose()

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

# how many times a failing getLogs range may be halved before we give up and surface it
_MAX_SPLIT_DEPTH = 8

# Transfers per alchemy_getAssetTransfers page. Our receiving addresses see a handful of
# payments a week, so one page is the whole answer in practice and the loop is for safety.
_TRANSFER_PAGE = 1000
# Enough pages to be a real safety net, few enough that a misbehaving endpoint cannot spin
# this forever.
_MAX_TRANSFER_PAGES = 20


class EvmRpcError(RuntimeError):
    """A JSON-RPC call returned an error object."""


class MethodUnsupported(EvmRpcError):
    """The endpoint does not implement this method at all — try a different approach."""


def _is_unsupported(error: str) -> bool:
    """Does this error mean "I do not have that method" rather than "not right now"?

    Only a permanent answer may switch the client to the slower path for the rest of its
    life; a timeout or a rate limit must not, or one bad minute costs every later scan.
    """
    text = error.lower()
    return (
        "-32601" in text
        or "method not found" in text
        or "not supported" in text
        or "unsupported method" in text
        or "does not exist" in text
    )


def _to_int(hex_str: str | None) -> int:
    if not hex_str:
        return 0
    return int(hex_str, 16)


def _addr_topic(address: str) -> str:
    """Left-pad a 20-byte address into a 32-byte log topic (lowercased)."""
    return "0x" + address[2:].lower().rjust(64, "0")


def _topic_to_address(topic: str) -> str:
    return "0x" + topic[-40:]


def _log_index_of(entry: dict) -> int:
    """Log index out of uniqueId ("0xhash:log:154"), or 0 for a top-level transfer."""
    unique = str(entry.get("uniqueId") or "")
    marker = ":log:"
    if marker in unique:
        tail = unique.rsplit(marker, 1)[1]
        if tail.isdigit():
            return int(tail)
    return 0


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
        # The widest getLogs span this endpoint has been seen to refuse. Providers publish
        # wildly different caps — Alchemy's free tier allows ten blocks — and the only
        # reliable way to learn one is to be told. Remembering it turns a permanent limit
        # from a failure on every single call into a failure once per process.
        self._log_span_cap: int | None = None
        # None until we have asked. False once an endpoint has said it does not
        # implement the transfers API, which is a permanent property of that endpoint
        # — unlike a timeout, which must never demote the client for the rest of its
        # life.
        self._has_transfers_api: bool | None = None

    async def _rpc(self, method: str, params: list) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        data = await self._http.post(self._endpoint, json=payload)
        if isinstance(data, dict) and data.get("error"):
            message = f"{method}: {data['error']}"
            if _is_unsupported(message):
                raise MethodUnsupported(message)
            raise EvmRpcError(message)
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
            # One question — "what arrived at this address" — instead of a filtered log
            # query per ten blocks, or, for the native coin, a walk that fetched every
            # block in the window one at a time. Alchemy answers it over any span, so a
            # window that used to cost hundreds of calls costs one. An endpoint without
            # the method says so once and gets the standard path from then on.
            if self._has_transfers_api is not False:
                try:
                    transfers += await self._scan_transfers(method, from_block, to_block, head)
                    self._has_transfers_api = True
                    continue
                except MethodUnsupported:
                    self._has_transfers_api = False
            if spec.token_contract:
                transfers += await self._scan_token(method, from_block, to_block, head)
            elif spec.is_native:
                transfers += await self._scan_native(method, from_block, to_block, head)
        return transfers

    async def _scan_transfers(
        self, method: MethodConfig, from_block: int, to_block: int, head: int
    ) -> list[IncomingTransfer]:
        """Inbound transfers on one rail, asked for as a question about the address.

        Amounts come from rawContract.value — base units in hex — never from the `value`
        field beside it, which is a JSON float. The watcher matches an invoice on the exact
        quoted amount, and a float has already cost this project a payment that never
        matched.

        Decimals come from our own AssetSpec rather than the response, for the same reason
        the log scan re-checks the emitting contract: what a rail is worth is our fact, not
        the endpoint's.
        """
        spec = method.spec
        target = method.address.lower()
        contract = (spec.token_contract or "").lower()
        params: dict[str, Any] = {
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "toAddress": method.address,
            "withMetadata": False,
            "excludeZeroValue": True,
            "order": "asc",
            "maxCount": hex(_TRANSFER_PAGE),
            "category": ["erc20"] if contract else ["external"],
        }
        if contract:
            params["contractAddresses"] = [spec.token_contract]

        out: list[IncomingTransfer] = []
        page_key: str | None = None
        for _ in range(_MAX_TRANSFER_PAGES):
            if page_key:
                params["pageKey"] = page_key
            result = await self._rpc("alchemy_getAssetTransfers", [params])
            # An answer without a transfers list is not an empty answer. Some proxies
            # return null for a method they do not implement rather than an error, and
            # reading that as "nothing arrived" would switch payment detection off in
            # silence — the worst outcome available here. Caught by its own test.
            if not isinstance(result, dict) or "transfers" not in result:
                raise MethodUnsupported("alchemy_getAssetTransfers: no transfers in reply")
            for entry in result.get("transfers") or []:
                found = self._transfer_from_entry(entry, method, target, contract, head)
                if found is not None:
                    out.append(found)
            page_key = result.get("pageKey")
            if not page_key:
                break
        return out

    def _transfer_from_entry(
        self, entry: dict, method: MethodConfig, target: str, contract: str, head: int
    ) -> IncomingTransfer | None:
        """One response row as a transfer, or None when it is not one we asked for.

        Everything is re-checked rather than trusted, exactly as the log scan re-checks the
        emitting contract: a filter we send is a request, not a guarantee, and an endpoint
        answering with somebody else's transfer would otherwise credit an invoice.
        """
        spec = method.spec
        if str(entry.get("to") or "").lower() != target:
            return None
        raw = entry.get("rawContract") or {}
        raw_contract = str(raw.get("address") or "").lower()
        if contract:
            if raw_contract != contract:
                return None
        elif raw_contract:
            return None  # asked for the native coin and got a token
        base_units = _to_int(raw.get("value"))
        amount = Decimal(base_units) / (Decimal(10) ** spec.decimals)
        if amount <= 0:
            return None
        block_number = _to_int(entry.get("blockNum"))
        return IncomingTransfer(
            chain=self.chain,
            asset=spec.asset,
            network=spec.network,
            txid=str(entry.get("hash")),
            to_address=method.address,
            amount=amount,
            # uniqueId is "<hash>:log:<n>" for a token and "<hash>:external" for the native
            # coin. The ledger dedupes on (txid, log_index), and a top-level transfer has no
            # log of its own, so zero is both true and unique there.
            log_index=_log_index_of(entry),
            from_address=str(entry.get("from") or "") or None,
            block_number=block_number,
            confirmations=max(1, head - block_number + 1) if block_number else 1,
        )

    async def _get_logs(
        self, *, from_block: int, to_block: int, address: str, topics: list, depth: int = 0
    ) -> list:
        """eth_getLogs with automatic range splitting.

        Providers cap getLogs differently (block span, result count, archive depth) and
        answer with an error rather than a partial result. Measured on public testnet RPCs:
        Sepolia/publicnode serves ~50 blocks then demands a token, and the BSC data-seed
        node refuses even a 5-block span. Without splitting, one such error aborts the whole
        tick and the cursor never advances — the chain silently stops being watched. So on
        failure we halve the range and retry, down to a single block.
        """
        span = to_block - from_block
        too_wide = self._log_span_cap is not None and span >= self._log_span_cap
        params = [
            {
                "fromBlock": hex(from_block),
                "toBlock": hex(to_block),
                "address": address,
                "topics": topics,
            }
        ]
        try:
            if too_wide:
                # Already known to be refused. Asking anyway would spend a request to be
                # told something this client was told before.
                raise EvmRpcError(f"span {span} at or above the learned cap")
            return list(await self._rpc("eth_getLogs", params) or [])
        except EvmRpcError:
            if from_block >= to_block or depth >= _MAX_SPLIT_DEPTH:
                raise
            if not too_wide:
                # Narrower than anything that failed before, and it still failed: this is
                # the new ceiling.
                self._log_span_cap = min(self._log_span_cap or span, span)
            mid = from_block + (to_block - from_block) // 2
            left = await self._get_logs(
                from_block=from_block, to_block=mid, address=address,
                topics=topics, depth=depth + 1,
            )
            right = await self._get_logs(
                from_block=mid + 1, to_block=to_block, address=address,
                topics=topics, depth=depth + 1,
            )
            return left + right

    async def _scan_token(
        self, method: MethodConfig, from_block: int, to_block: int, head: int
    ) -> list[IncomingTransfer]:
        spec = method.spec
        logs = await self._get_logs(
            from_block=from_block,
            to_block=to_block,
            address=spec.token_contract or "",
            topics=[_TRANSFER_TOPIC, None, _addr_topic(method.address)],
        )
        contract = (spec.token_contract or "").lower()
        out: list[IncomingTransfer] = []
        for entry in logs or []:
            # Re-verify the emitting contract and event signature instead of trusting
            # that the RPC honoured our filter — a hostile endpoint could return a log
            # from an arbitrary contract and have it accepted as a real USDT/USDC transfer.
            if str(entry.get("address", "")).lower() != contract:
                continue
            topics = entry.get("topics") or []
            if not topics or str(topics[0]).lower() != _TRANSFER_TOPIC:
                continue
            block_number = _to_int(entry.get("blockNumber"))
            amount = Decimal(_to_int(entry.get("data"))) / (Decimal(10) ** spec.decimals)
            if amount <= 0:
                continue
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

    async def scan_outgoing(
        self, *, from_block: int, to_block: int, source_address: str, token_contract: str,
        decimals: int = 6, asset: str = "USDT", network: str = "erc20",
    ) -> list[IncomingTransfer]:
        """Token transfers sent FROM our payout wallet (used to auto-confirm payouts).

        Same Transfer-event filter as the deposit scan, but matching on the *from* topic.
        The dataclass is reused as-is — ``to_address`` is the recipient, ``from_address`` us.
        """
        head = await self._block_number()
        contract = token_contract.lower()
        logs = await self._get_logs(
            from_block=from_block,
            to_block=to_block,
            address=token_contract,
            topics=[_TRANSFER_TOPIC, _addr_topic(source_address), None],
        )
        out: list[IncomingTransfer] = []
        for entry in logs or []:
            if str(entry.get("address", "")).lower() != contract:
                continue
            topics = entry.get("topics") or []
            if not topics or str(topics[0]).lower() != _TRANSFER_TOPIC or len(topics) < 3:
                continue
            amount = Decimal(_to_int(entry.get("data"))) / (Decimal(10) ** decimals)
            if amount <= 0:
                continue
            block_number = _to_int(entry.get("blockNumber"))
            out.append(
                IncomingTransfer(
                    chain=self.chain,
                    asset=asset,
                    network=network,
                    txid=str(entry.get("transactionHash")),
                    to_address=_topic_to_address(topics[2]),
                    amount=amount,
                    log_index=_to_int(entry.get("logIndex")),
                    from_address=source_address,
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

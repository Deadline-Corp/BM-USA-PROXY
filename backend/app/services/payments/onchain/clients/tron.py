"""Tron chain client (USDT-TRC20 + native TRX) via the TronGrid HTTP API.

Cursor semantics for Tron are **milliseconds** (block timestamp), not block numbers:
``get_block_height`` returns the latest block's timestamp and ``scan`` queries the
account-transactions endpoints by ``min_timestamp``/``max_timestamp``. Confirmation depth
is still computed from block numbers. Only ``only_to`` + ``only_confirmed`` results are
requested, so the query itself guarantees the transfer is to our address and finalized.

Requires a TronGrid endpoint and (recommended) a ``TRON-PRO-API-KEY`` for rate limits.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from app.core.logging import log
from app.services.payments.onchain.chain_client import IncomingTransfer
from app.services.payments.onchain.clients.http import HttpxJson, JsonHttp
from app.services.payments.onchain.config import MethodConfig

_TRON_BLOCK_MS = 3000  # ~3s block time — used to estimate TRC20 confirmation depth


class TronClient:
    chain = "tron"

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str | None = None,
        http: JsonHttp | None = None,
        page_limit: int = 200,
        max_pages: int = 20,
    ) -> None:
        self._base = endpoint.rstrip("/")
        self._api_key = api_key
        self._http = http or HttpxJson()
        self._page_limit = page_limit
        self._max_pages = max_pages

    def _headers(self) -> dict[str, str]:
        return {"TRON-PRO-API-KEY": self._api_key} if self._api_key else {}

    async def _now_block(self) -> tuple[int, int]:
        """Return (block_number, block_timestamp_ms) of the current head."""
        data = await self._http.post(
            f"{self._base}/wallet/getnowblock", json={}, headers=self._headers()
        )
        raw = (data or {}).get("block_header", {}).get("raw_data", {})
        return int(raw.get("number", 0)), int(raw.get("timestamp", 0))

    async def get_block_height(self) -> int:
        _, timestamp_ms = await self._now_block()
        return timestamp_ms

    async def scan(
        self, *, from_block: int, to_block: int, methods: Sequence[MethodConfig]
    ) -> list[IncomingTransfer]:
        now_number, now_ts = await self._now_block()
        transfers: list[IncomingTransfer] = []
        for method in methods:
            spec = method.spec
            if spec.network == "trc20" and spec.token_contract:
                transfers += await self._scan_trc20(
                    method, from_block, to_block, now_ts
                )
            elif spec.network == "native" and spec.asset == "TRX":
                transfers += await self._scan_trx(method, from_block, to_block, now_number)
        return transfers

    async def _scan_trc20(
        self, method: MethodConfig, min_ts: int, max_ts: int, now_ts: int
    ) -> list[IncomingTransfer]:
        spec = method.spec
        url = f"{self._base}/v1/accounts/{method.address}/transactions/trc20"
        params: dict = {
            "only_to": "true",
            "only_confirmed": "true",
            "contract_address": spec.token_contract,
            "min_timestamp": min_ts,
            "max_timestamp": max_ts,
            "limit": self._page_limit,
            "order_by": "block_timestamp,asc",
        }
        out: list[IncomingTransfer] = []
        for _ in range(self._max_pages):
            data = await self._http.get(url, params=params, headers=self._headers())
            for item in (data or {}).get("data", []):
                if item.get("type") not in (None, "Transfer"):
                    continue
                token = item.get("token_info") or {}
                decimals = int(token.get("decimals", spec.decimals))
                try:
                    amount = Decimal(str(item["value"])) / (Decimal(10) ** decimals)
                except (KeyError, ArithmeticError):
                    continue
                block_ts = int(item.get("block_timestamp", now_ts))
                out.append(
                    IncomingTransfer(
                        chain=self.chain,
                        asset=spec.asset,
                        network=spec.network,
                        txid=str(item["transaction_id"]),
                        to_address=method.address,
                        amount=amount,
                        from_address=item.get("from"),
                        block_time=datetime.fromtimestamp(block_ts / 1000, tz=UTC),
                        confirmations=max(1, (now_ts - block_ts) // _TRON_BLOCK_MS),
                    )
                )
            fingerprint = ((data or {}).get("meta") or {}).get("fingerprint")
            if not fingerprint:
                break
            params["fingerprint"] = fingerprint
        return out

    async def _scan_trx(
        self, method: MethodConfig, min_ts: int, max_ts: int, now_number: int
    ) -> list[IncomingTransfer]:
        url = f"{self._base}/v1/accounts/{method.address}/transactions"
        params: dict = {
            "only_to": "true",
            "only_confirmed": "true",
            "min_timestamp": min_ts,
            "max_timestamp": max_ts,
            "limit": self._page_limit,
            "order_by": "block_timestamp,asc",
        }
        out: list[IncomingTransfer] = []
        for _ in range(self._max_pages):
            data = await self._http.get(url, params=params, headers=self._headers())
            for tx in (data or {}).get("data", []):
                ret = (tx.get("ret") or [{}])[0].get("contractRet")
                if ret not in (None, "SUCCESS"):
                    continue
                contracts = (tx.get("raw_data") or {}).get("contract") or []
                if not contracts or contracts[0].get("type") != "TransferContract":
                    continue
                value = (contracts[0].get("parameter") or {}).get("value") or {}
                amount_sun = int(value.get("amount", 0))
                if amount_sun <= 0:
                    continue
                block_number = int(tx.get("blockNumber", 0)) or None
                confs = (now_number - block_number + 1) if block_number else 1
                out.append(
                    IncomingTransfer(
                        chain=self.chain,
                        asset="TRX",
                        network="native",
                        txid=str(tx["txID"]),
                        to_address=method.address,
                        amount=Decimal(amount_sun) / (Decimal(10) ** 6),
                        from_address=value.get("owner_address"),
                        block_number=block_number,
                        confirmations=max(1, confs),
                    )
                )
            fingerprint = ((data or {}).get("meta") or {}).get("fingerprint")
            if not fingerprint:
                break
            params["fingerprint"] = fingerprint
        return out

    async def confirmations(self, txid: str, *, block_number: int | None = None) -> int:
        if block_number is None:
            info = await self._http.post(
                f"{self._base}/wallet/gettransactioninfobyid",
                json={"value": txid},
                headers=self._headers(),
            )
            raw_block = (info or {}).get("blockNumber")
            block_number = int(raw_block) if raw_block else None
        if not block_number:
            return 0
        now_number, _ = await self._now_block()
        return max(0, now_number - block_number + 1)

    async def aclose(self) -> None:
        try:
            await self._http.aclose()
        except Exception:  # pragma: no cover - best-effort cleanup
            log.debug("tron.aclose_failed")

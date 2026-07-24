"""UTXO chain client (Bitcoin + Litecoin) over the Esplora REST API.

One engine serves both chains — Bitcoin via mempool.space and Litecoin via a Litecoin
Esplora instance; both expose the identical Esplora API, only the endpoint differs.

Detection watches the receiving address directly (``GET /address/:addr/txs``) and treats
each output paying that address as an incoming transfer, disambiguated by output index.
Cursor = block height; confirmations = tip − confirmed block + 1 (mempool = 0-conf, which
the watcher records as "confirming" until it lands and ``finalize_confirming`` catches it).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from app.services.payments.onchain.chain_client import IncomingTransfer
from app.services.payments.onchain.clients.http import HttpxJson, JsonHttp
from app.services.payments.onchain.config import MethodConfig

_SATS = Decimal(10) ** 8


class UtxoClient:
    def __init__(
        self,
        *,
        chain: str,
        endpoint: str,
        http: JsonHttp | None = None,
        max_pages: int = 10,
    ) -> None:
        self.chain = chain
        self._base = endpoint.rstrip("/")
        self._http = http or HttpxJson()
        self._max_pages = max_pages

    async def _tip(self) -> int:
        return int(await self._http.get(f"{self._base}/blocks/tip/height"))

    async def get_block_height(self) -> int:
        return await self._tip()

    async def _address_txs(self, address: str, min_height: int) -> list[dict]:
        """Fetch recent txs for an address, paginating until below the cursor height."""
        collected: list[dict] = []
        url = f"{self._base}/address/{address}/txs"
        for _ in range(self._max_pages):
            page: Any = await self._http.get(url)
            if not page:
                break
            collected.extend(page)
            last = page[-1]
            status = last.get("status") or {}
            height = status.get("block_height")
            # stop once the page tail is confirmed and older than the cursor
            if status.get("confirmed") and height is not None and height < min_height:
                break
            url = f"{self._base}/address/{address}/txs/chain/{last.get('txid')}"
        return collected

    async def scan(
        self, *, from_block: int, to_block: int, methods: Sequence[MethodConfig]
    ) -> list[IncomingTransfer]:
        tip = await self._tip()
        transfers: list[IncomingTransfer] = []
        for method in methods:
            spec = method.spec
            if not spec.is_native:
                continue
            for tx in await self._address_txs(method.address, from_block):
                status = tx.get("status") or {}
                confirmed = bool(status.get("confirmed"))
                height = status.get("block_height")
                if confirmed and height is not None and height < from_block:
                    continue  # older than cursor — stragglers handled by finalize_confirming
                confs = (tip - height + 1) if (confirmed and height) else 0
                for index, vout in enumerate(tx.get("vout", [])):
                    if vout.get("scriptpubkey_address") != method.address:
                        continue
                    value = int(vout.get("value", 0))
                    if value <= 0:
                        continue
                    transfers.append(
                        IncomingTransfer(
                            chain=self.chain,
                            asset=spec.asset,
                            network="native",
                            txid=str(tx.get("txid")),
                            to_address=method.address,
                            amount=Decimal(value) / _SATS,
                            log_index=index,
                            block_number=height,
                            confirmations=max(0, confs),
                        )
                    )
        return transfers

    async def confirmations(self, txid: str, *, block_number: int | None = None) -> int:
        tx = await self._http.get(f"{self._base}/tx/{txid}")
        status = (tx or {}).get("status") or {}
        if not status.get("confirmed"):
            return 0
        height = status.get("block_height")
        if not height:
            return 0
        tip = await self._tip()
        return max(0, tip - int(height) + 1)

    async def aclose(self) -> None:
        await self._http.aclose()

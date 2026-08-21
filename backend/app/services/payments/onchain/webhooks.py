"""Address-activity webhooks: the chain tells us money arrived, instead of us asking.

A plain JSON-RPC node cannot be subscribed to. It has no memory of what we asked last
time, so every scan has to name a block range and the watcher has to keep asking — which
is the whole reason the pool of RPC calls exists at all. A provider webhook removes the
asking: Alchemy posts here the moment one of our receiving addresses is touched.

**The payload is a doorbell, not a receipt.** Nothing in it credits anything. It carries a
float amount, it can be replayed, and a signature only proves it came from the webhook we
registered — not that the transaction is final, or ours, or worth what it says. So a valid
delivery does exactly one thing: it marks the chain as worth looking at, and the watcher
then reads the chain itself, the same way it always has. Every rule about confirmations,
exact amounts and idempotency stays where it already is.

That also makes a missed webhook harmless. The poll remains, only slower on a chain whose
webhooks are arriving — see `scan_is_due`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from app.core.config import settings
from app.core.logging import log
from app.core.redis import redis_client

# Alchemy's network names -> our chain keys. Only the two we run on EVM; a delivery for
# anything else is dropped rather than guessed at.
_NETWORKS: dict[str, str] = {
    "ETH_MAINNET": "ethereum",
    "ETH_SEPOLIA": "ethereum",
    "BNB_MAINNET": "bsc",
    "BNB_TESTNET": "bsc",
}

# "Look now" — set by a delivery, cleared by the scan that honours it.
_WAKE = "onchain:wake:{chain}"
# "Deliveries are arriving for this chain." Its lifetime is what decides whether the poll
# may slow down, so it must outlast a quiet stretch comfortably: an address nobody pays is
# an address nobody rings the bell for, and treating that silence as a broken webhook would
# put the polling back exactly when it is least useful.
_ALIVE = "onchain:webhook_alive:{chain}"
_ALIVE_TTL = 24 * 3600
_WAKE_TTL = 3600

# How long a chain with live webhooks may go unscanned while nothing rings. The safety net
# behind a missed delivery, and the number that decides what this saves: five minutes
# instead of fifteen seconds is twenty times fewer scans while an invoice is open.
QUIET_SCAN_INTERVAL = 300
_LAST_SCAN = "onchain:last_scan:{chain}"


def signing_keys() -> list[str]:
    """Every signing key we accept, from ALCHEMY_WEBHOOK_KEYS.

    A JSON object keyed by network, but read as a plain list of secrets: the network in the
    body cannot be trusted to pick a key, because picking the key is what decides whether
    to trust the body at all. Two HMACs is not a cost worth being clever about.
    """
    raw = settings.alchemy_webhook_keys
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        log.warning("onchain.webhook.keys_unparsable")
        return []
    if isinstance(parsed, dict):
        return [str(v) for v in parsed.values() if v]
    if isinstance(parsed, list):
        return [str(v) for v in parsed if v]
    return [str(parsed)] if parsed else []


def verify(raw_body: bytes, signature: str | None) -> bool:
    """Is this delivery signed by one of our webhooks?

    Compared in constant time, over the raw bytes — re-serialising the JSON first would
    change the payload and fail every time, which is the usual way this is got wrong.
    """
    if not signature:
        return False
    for key in signing_keys():
        digest = hmac.new(key.encode(), raw_body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(digest, signature):
            return True
    return False


def chain_of(payload: Any) -> str | None:
    """Which of our chains this delivery is about, or None if it is not one of them."""
    if not isinstance(payload, dict):
        return None
    event = payload.get("event")
    network = event.get("network") if isinstance(event, dict) else None
    return _NETWORKS.get(str(network or "").upper())


async def ring(chain: str) -> None:
    """Record that this chain is worth looking at, and that its webhooks are alive."""
    await redis_client.set(_WAKE.format(chain=chain), "1", ex=_WAKE_TTL)
    await redis_client.set(_ALIVE.format(chain=chain), "1", ex=_ALIVE_TTL)


async def scan_is_due(chain: str) -> bool:
    """May the watcher skip the expensive scan on this pass?

    Yes only while all three hold: this chain's webhooks are arriving, none has rung since
    the last scan, and the last scan is recent. Any doubt scans — the saving is worth a lot
    less than a payment nobody noticed, which is a thing that has already happened here.
    """
    if await redis_client.get(_WAKE.format(chain=chain)):
        return True
    if not await redis_client.get(_ALIVE.format(chain=chain)):
        return True  # no webhook to rely on — poll as before
    return not await redis_client.get(_LAST_SCAN.format(chain=chain))


async def note_scan(chain: str) -> None:
    """A scan just happened: clear the bell and start the quiet window."""
    await redis_client.delete(_WAKE.format(chain=chain))
    await redis_client.set(
        _LAST_SCAN.format(chain=chain), "1", ex=QUIET_SCAN_INTERVAL
    )

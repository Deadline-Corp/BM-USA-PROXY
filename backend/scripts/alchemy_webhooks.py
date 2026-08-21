"""Register (or refresh) Alchemy address-activity webhooks for our receiving addresses.

Run: python -m scripts.alchemy_webhooks            # show what exists
     python -m scripts.alchemy_webhooks --apply    # create/update to match the config

Needs ALCHEMY_AUTH_TOKEN (the dashboard token, "alcht_..." — not the RPC key) and a
reachable PUBLIC_BASE_URL. Prints the signing keys at the end; they go into
ALCHEMY_WEBHOOK_KEYS, which is what makes a delivery believable.

Kept as a script rather than something the app does on boot. It writes to an account we do
not own — the client's — and a deploy loop that silently recreates webhooks there is not a
thing anybody wants to debug at two in the morning.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
from app.core.config import settings
from app.core.db import SessionFactory
from app.services.payments.onchain.config import get_onchain_config
from app.services.payments.onchain.rails import refresh_rails

_API = "https://dashboard.alchemy.com/api"
# Our chains, as Alchemy names its networks.
_NETWORK_OF = {"ethereum": "ETH_MAINNET", "bsc": "BNB_MAINNET"}
_TESTNET_OF = {"ethereum": "ETH_SEPOLIA", "bsc": "BNB_TESTNET"}


def _auth_token() -> str:
    token = os.environ.get("ALCHEMY_AUTH_TOKEN", "").strip()
    if not token:
        sys.exit("ALCHEMY_AUTH_TOKEN is not set (the alcht_... dashboard token)")
    return token


def _callback_url() -> str:
    base = (os.environ.get("PUBLIC_BASE_URL") or settings.public_base_url or "").rstrip("/")
    if not base.startswith("https://"):
        sys.exit(f"PUBLIC_BASE_URL must be a public https URL, got {base!r}")
    return f"{base}/api/webhooks/alchemy"


async def _wanted() -> dict[str, list[str]]:
    """Network -> the receiving addresses we want watched on it."""
    async with SessionFactory() as session:
        await refresh_rails(session)
    config = get_onchain_config()
    testnet = str(config.network).lower() == "testnet"
    names = _TESTNET_OF if testnet else _NETWORK_OF

    wanted: dict[str, list[str]] = {}
    for chain, network in names.items():
        addresses = sorted(
            {m.address for m in config.methods_for_chain(chain) if m.address}
        )
        if addresses:
            wanted[network] = addresses
    return wanted


async def main() -> None:
    apply = "--apply" in sys.argv
    token = _auth_token()
    url = _callback_url()
    wanted = await _wanted()
    if not wanted:
        sys.exit("no EVM rails configured — nothing to watch")

    headers = {"X-Alchemy-Token": token, "Content-Type": "application/json"}
    keys: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=30) as http:
        existing = (await http.get(f"{_API}/team-webhooks", headers=headers)).json()
        mine = {
            hook["network"]: hook
            for hook in existing.get("data", [])
            if hook.get("webhook_url") == url and hook.get("webhook_type") == "ADDRESS_ACTIVITY"
        }

        for network, addresses in wanted.items():
            hook = mine.get(network)
            print(f"\n{network}: {len(addresses)} address(es)")
            for address in addresses:
                print(f"    {address}")

            if hook is not None:
                keys[network] = hook.get("signing_key", "")
                print(f"  already registered (id {hook.get('id')})")
                if not apply:
                    continue
                # Addresses are replaced wholesale rather than diffed: the config is the
                # intent, and a webhook watching an address we no longer accept is a
                # delivery nobody can act on.
                patch = await http.patch(
                    f"{_API}/update-webhook-addresses",
                    headers=headers,
                    json={"webhook_id": hook["id"], "addresses": addresses},
                )
                print(f"  addresses updated: {patch.status_code}")
                continue

            if not apply:
                print("  MISSING — rerun with --apply to create")
                continue
            created = await http.post(
                f"{_API}/create-webhook",
                headers=headers,
                json={
                    "network": network,
                    "webhook_type": "ADDRESS_ACTIVITY",
                    "webhook_url": url,
                    "addresses": addresses,
                },
            )
            if created.status_code >= 300:
                print(f"  FAILED {created.status_code}: {created.text[:200]}")
                continue
            data = created.json().get("data", {})
            keys[network] = data.get("signing_key", "")
            print(f"  created (id {data.get('id')})")

    print(f"\ncallback: {url}")
    if keys:
        print("\nALCHEMY_WEBHOOK_KEYS=" + json.dumps(keys))
        print("(set that on the api service — without it every delivery is refused)")


if __name__ == "__main__":
    asyncio.run(main())

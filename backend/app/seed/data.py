"""Static seed data: tariffs, locations, FAQ, and default app settings.

Real values from the client's live site (08_Real_client_data) and the ToS gate.
"""

from __future__ import annotations

from pathlib import Path

_TOS_PATH = Path(__file__).parent / "tos_v1.md"


def tos_text_v1() -> str:
    return _TOS_PATH.read_text(encoding="utf-8")


# code, name, kind, duration_minutes, price_usd, max_per_user, max_user_swaps, auto_issue, sort
TARIFFS: list[dict] = [
    {"code": "trial", "name": "Trial (1 hour)", "kind": "auto", "duration_minutes": 60,
     "price_usd": "0", "max_per_user": 1, "max_user_swaps": 1, "auto_issue": True, "sort_order": 10,
     "description": "1 free 1-hour test per user. One connection swap included."},
    {"code": "daily", "name": "Daily", "kind": "auto", "duration_minutes": 1440,
     "price_usd": "10", "max_per_user": None, "max_user_swaps": 0, "auto_issue": True,
     "sort_order": 20, "description": "24 hours, unlimited 5G."},
    {"code": "weekly", "name": "Weekly", "kind": "auto", "duration_minutes": 10080,
     "price_usd": "23", "max_per_user": None, "max_user_swaps": 0, "auto_issue": True,
     "sort_order": 30, "description": "7 days, unlimited 5G."},
    {"code": "monthly", "name": "Monthly", "kind": "auto", "duration_minutes": 43200,
     "price_usd": "85", "max_per_user": None, "max_user_swaps": 0, "auto_issue": True,
     "sort_order": 40, "description": "30 days, unlimited 5G."},
    {"code": "reseller", "name": "Reseller / wholesale", "kind": "manual", "duration_minutes": None,
     "price_usd": "0", "max_per_user": None, "max_user_swaps": 0, "auto_issue": False,
     "sort_order": 50, "description": "Custom volume pricing — submit a request."},
]

# (city, state_code, sort)
LOCATIONS: list[tuple[str, str, int]] = [
    ("Seattle", "WA", 10),
    ("Los Angeles", "CA", 20),
    ("Las Vegas", "NV", 30),
    ("Portland", "OR", 40),
    ("Denver", "CO", 50),
    ("Phoenix", "AZ", 60),
    ("Dallas", "TX", 70),
    ("Miami", "FL", 80),
    ("Chicago", "IL", 90),
]

# category, question, answer, sort
FAQ: list[tuple[str, str, str, int]] = [
    ("basics", "What is a mobile proxy?",
     "A mobile proxy routes your traffic through a real US phone on a carrier network "
     "(T-Mobile, Verizon, AT&T), giving you a genuine mobile IP address.", 10),
    ("basics", "Private or shared?",
     "All proxies are private/dedicated — one connection is used by one client at a time.", 20),
    ("connect", "Which protocols are supported?",
     "SOCKS5, HTTP, plus OpenVPN (UDP) and WireGuard configs. IPv4 and IPv6.", 30),
    ("connect", "How does IP rotation work?",
     "Rotate your IP any time from the app — it reboots the phone remotely and assigns a "
     "fresh mobile IP.", 40),
    ("billing", "How do I pay?",
     "Crypto (USDT, USDC, BTC, ETH). Your access is issued automatically right after payment "
     "confirms.", 50),
    ("billing", "Is there a free trial?",
     "Yes — 1 free 1-hour test per user, with one connection swap if the first doesn't suit you.",
     60),
]


def default_settings(tos_version: int = 1) -> dict[str, object]:
    return {
        "referral_pct": 20,
        "referral_hold_days": 14,
        "referral_min_payout_usd": 20,
        "invoice_ttl_minutes": 60,
        "rotation_cooldown_sec": 60,
        "pool_low_watermark": 10,
        "attribution": {"mode": "first_touch", "rebind_window_hours": 720},
        "tos": {
            "version": tos_version,
            "text_md": tos_text_v1(),
            "questions": [
                {"id": "email", "label": "Email", "type": "email", "required": True},
            ],
        },
    }

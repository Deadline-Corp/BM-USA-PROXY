"""Which mobile carrier an exit IP belongs to.

The rule is the client's, taken from how their own farm is addressed: Verizon hands out
174.x, T-Mobile 172.x, and everything else on the account is AT&T. It is a convention
about *this* pool, not a fact about the internet — 172.x is mostly private space
(172.16/12) and 174.x belongs to many networks besides Verizon — so it must never be
applied to an address that did not come from one of the client's phones.

It lives here, in one place, because two callers need the same answer: the pool sync
stamps it onto every connection, and the access screen derives it from the live exit IP.
Two copies of this table would drift, and the buyer would see one carrier on the catalogue
card and another on the access they just bought.
"""

from __future__ import annotations

_BY_FIRST_OCTET: dict[str, str] = {
    "172": "T-Mobile",
    "174": "Verizon",
}

DEFAULT_CARRIER = "AT&T"


def carrier_from_ip(ip: str | None) -> str | None:
    """Exit IP → carrier name, or None when there is no address to judge by.

    None and "unknown" are different answers: None means "we do not know yet" (the phone
    reported no address) and must not be shown as AT&T, which is what a bare default
    would do.
    """
    if not ip:
        return None
    first = ip.strip().split(".", 1)[0]
    if not first.isdigit():
        return None
    return _BY_FIRST_OCTET.get(first, DEFAULT_CARRIER)

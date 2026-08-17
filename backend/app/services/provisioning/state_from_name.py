"""Reading a US state out of a connection's name.

The client names phones with the state they are sold as — `att113_NV`, `verizon_CA_04` — and
that name is the only place a 2000-phone farm carries the information: iproxy's API exposes
neither the console's groups nor a state field, and filling in a per-device description
would be the same work over again.

The name is written by humans, so this reads conservatively. It only accepts a two-letter
token that is a real state code, and only when the name yields exactly one candidate —
guessing between two is worse than not guessing, because the result is what a customer is
sold as their location.
"""

from __future__ import annotations

import re

# All 50 plus DC. The full list, not just the states sold today: a phone named for a state
# the client has not mapped yet should be recognised as that state and reported as
# unmapped, rather than silently read as "no state at all".
US_STATE_CODES: frozenset[str] = frozenset(
    # fmt: off
    [
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID",
        "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO",
        "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
        "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    ]
    # fmt: on
)

# Splits on anything that is not a letter or digit, and also between a letter run and a
# digit run: "att113_NV" gives att, 113, NV, and "NV02" gives NV, 02.
_TOKEN = re.compile(r"[A-Za-z]+|[0-9]+")


def state_from_name(name: str | None) -> str | None:
    """The state a connection's name declares, or None when it declares none.

    None covers three different situations on purpose — no two-letter token, no token that
    is a state, or more than one distinct state named — because the caller does the same
    thing in all three: fall back to the exit IP's own city.

    Case-insensitive, since `att113_nv` and `ATT113_NV` are the same phone to whoever typed
    it. A two-letter word that happens to be a state code is still read as one: "in", "or"
    and "me" are states, and a name like `proxy_or_backup` would resolve to Oregon. That is
    accepted — the alternative is a dictionary of English words, and the client's naming is
    machine-generated with the state deliberately in it.
    """
    if not name:
        return None
    found = {t.upper() for t in _TOKEN.findall(name) if len(t) == 2 and t.upper() in US_STATE_CODES}
    return found.pop() if len(found) == 1 else None

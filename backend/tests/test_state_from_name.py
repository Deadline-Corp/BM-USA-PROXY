"""Reading the state a phone is sold as out of its name.

iproxy's API exposes neither the console's groups nor a state field, and a 2000-phone farm
cannot have a description filled in per device — so the client writes the state into the
connection name (`att113_NV`) and this is what reads it back.

The result is what a customer is told their proxy's location is, so it reads
conservatively: a real state code, and only when the name yields exactly one.
"""

from __future__ import annotations

import pytest
from app.services.provisioning.state_from_name import state_from_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # The client's own convention, and the shapes around it.
        ("att113_NV", "NV"),
        ("att113_nv", "NV"),  # whoever typed it did not hold shift
        ("verizon_CA_04", "CA"),
        ("NV02", "NV"),  # no separator: a letter run beside a digit run
        ("tmobile-il-7", "IL"),
        ("WA", "WA"),
        # Nothing to read.
        ("test_bot_1", None),
        ("", None),
        (None, None),
        ("att113_XX", None),  # two letters, not a state
        ("phone_1_2", None),
        # Ambiguous is not guessed: being wrong here sells somebody the wrong city.
        ("att_NV_CA", None),
        # The same state twice is not ambiguous.
        ("NV_att_nv", "NV"),
    ],
)
def test_it_reads_a_state_only_when_the_name_declares_exactly_one(
    name: str | None, expected: str | None
) -> None:
    assert state_from_name(name) == expected


def test_a_two_letter_word_that_is_a_state_is_still_read_as_one() -> None:
    """Documented, not accidental: "or", "in" and "me" are states.

    The alternative is a dictionary of English words, and the client's names are machine
    generated with the state deliberately in them — so this is the trade that was chosen.
    """
    assert state_from_name("proxy_or_backup") == "OR"

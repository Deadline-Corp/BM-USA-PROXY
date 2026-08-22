"""Shared ledger status constants.

These status sets were duplicated across ``watcher.py`` and ``manual_resolution.py``.
Centralising them here prevents drift: a new terminal state added to the watcher must
not be missed by the manual-resolution guard, and vice-versa.
"""

from __future__ import annotations

# A transfer in one of these ledger states is settled — don't reprocess it.
# Used by the watcher to skip deposits that have already been handled.
TERMINAL_LEDGER: frozenset[str] = frozenset(
    {"paid", "overpaid", "underpaid", "unmatched", "expired_deposit", "orphaned", "reorg_rollback"}
)

# States where the deposit is still waiting for a human decision.
# Used by manual_resolution to accept operator input.
RESOLVABLE: tuple[str, ...] = ("unmatched", "underpaid", "expired_deposit", "orphaned")

# States that already settled — re-resolving would double-credit.
# Used by manual_resolution to reject operator input.
SETTLED: tuple[str, ...] = ("paid", "matched", "overpaid")
"""TTL-cached wrapper for ``refresh_rails``.

``refresh_rails`` is called from 5+ places (twa/router, orders, jobs, admin) — each one
opens a session, reads two app_settings rows, and calls ``set_rails_override`` /
``set_payout_override``. The reads are cheap (indexed lookups) but redundant within a
single request cycle: a buyer who hits ``/catalog`` and then ``POST /orders`` triggers
two full refreshes in under a second, and the config has not changed in that window.

This module provides ``refresh_rails_cached`` — a process-global 10s TTL cache that
fronts ``refresh_rails``. The first call in a burst does the real refresh; subsequent
calls within the TTL are no-ops. The cache is cleared explicitly by
``config.reset_config_cache`` (tests) and by ``rails.save_rails`` (after a console save,
so the new rails go live immediately rather than after the TTL expires).

The worker process has its own separate cache (different process, different global),
which is correct — a console save in the API process does not reach the worker until its
own TTL expires, which is bounded to 10s and acceptable for a cron that runs every 15s.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app.services.payments.onchain.rails import refresh_rails

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_CACHE_TTL_SECONDS: float = 10.0
_last_refresh_ts: float = 0.0


async def refresh_rails_cached(session: AsyncSession) -> None:
    """Call ``refresh_rails`` at most once per ``_CACHE_TTL_SECONDS`` window.

    Falls through to the real refresh when the TTL has elapsed or after an explicit
    ``invalidate_refresh_rails_cache`` call. Safe to call from any context that has a
    session — the session is only used on a cache miss.
    """
    global _last_refresh_ts
    now = time.monotonic()
    if now - _last_refresh_ts < _CACHE_TTL_SECONDS:
        return
    await refresh_rails(session)
    _last_refresh_ts = now


def invalidate_refresh_rails_cache() -> None:
    """Force the next ``refresh_rails_cached`` call to do a real refresh."""
    global _last_refresh_ts
    _last_refresh_ts = 0.0
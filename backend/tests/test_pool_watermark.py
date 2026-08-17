"""Low-stock alerting: when it speaks, when it stays quiet, and how often it looks.

The threshold setting shipped with the console and was read by nothing for months, so
these pin the behaviour rather than trusting it: an alert on the way down, silence while
nothing changes, one word when it recovers, and a check cadence an operator can change
from Settings without a redeploy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Connection, Location
from app.services import settings as settings_svc
from app.services.maintenance import check_pool_watermark


async def _pool(session, *, free_phones: int) -> None:
    loc = Location(city="Boise", state_code="ID")
    session.add(loc)
    await session.flush()
    for i in range(free_phones):
        session.add(
            Connection(
                iproxy_connection_id=f"wm-{i}",
                location_id=loc.id,
                carrier="Verizon",
                is_sellable=True,
                online_status="online",
            )
        )
    await session.flush()


class _Recorder:
    """Captures what would have gone to Telegram."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def __call__(self, session, text: str) -> int:
        self.sent.append(text)
        return 1


async def test_it_alerts_when_stock_is_below_the_threshold(session, monkeypatch) -> None:
    rec = _Recorder()
    monkeypatch.setattr("app.services.ops_alerts.notify_ops", rec)
    await _pool(session, free_phones=2)
    await settings_svc.set_value(session, "pool_low_watermark", 6)
    await session.flush()

    result = await check_pool_watermark(session)

    assert result == {"free": 2, "threshold": 6, "alerted": True}
    assert "2 proxies free" in rec.sent[0]
    assert "threshold is 6" in rec.sent[0]


async def test_it_does_not_repeat_while_stock_stays_low(session, monkeypatch) -> None:
    """Otherwise the same message arrives every few minutes until somebody mutes the bot."""
    rec = _Recorder()
    monkeypatch.setattr("app.services.ops_alerts.notify_ops", rec)
    await _pool(session, free_phones=2)
    await settings_svc.set_value(session, "pool_low_watermark", 6)
    await settings_svc.set_value(session, "pool_check_interval_minutes", 1)
    await session.flush()

    await check_pool_watermark(session)
    await check_pool_watermark(session)

    assert len(rec.sent) == 1


async def test_recovery_is_announced_once(session, monkeypatch) -> None:
    rec = _Recorder()
    monkeypatch.setattr("app.services.ops_alerts.notify_ops", rec)
    await _pool(session, free_phones=2)
    await settings_svc.set_value(session, "pool_low_watermark", 2)
    await settings_svc.set_value(session, "pool_check_interval_minutes", 1)
    await settings_svc.set_value(
        session,
        "pool_low_alert_state",
        {"low": True, "notified_at": datetime.now(UTC).isoformat()},
    )
    await session.flush()

    result = await check_pool_watermark(session)

    assert result["recovered"] is True
    assert "recovered" in rec.sent[0].lower()


async def test_the_check_interval_is_honoured(session, monkeypatch) -> None:
    """The cron fires every minute; this is what makes it look only as often as asked."""
    rec = _Recorder()
    monkeypatch.setattr("app.services.ops_alerts.notify_ops", rec)
    await _pool(session, free_phones=2)
    await settings_svc.set_value(session, "pool_low_watermark", 6)
    await settings_svc.set_value(session, "pool_check_interval_minutes", 30)
    await session.flush()

    first = await check_pool_watermark(session)
    second = await check_pool_watermark(session)

    assert first["alerted"] is True
    assert second == {"skipped": "not due"}


async def test_an_elapsed_interval_lets_it_look_again(session, monkeypatch) -> None:
    rec = _Recorder()
    monkeypatch.setattr("app.services.ops_alerts.notify_ops", rec)
    await _pool(session, free_phones=2)
    await settings_svc.set_value(session, "pool_low_watermark", 6)
    await settings_svc.set_value(session, "pool_check_interval_minutes", 30)
    await settings_svc.set_value(
        session,
        "pool_low_alert_state",
        {
            "low": True,
            "notified_at": (datetime.now(UTC) - timedelta(hours=7)).isoformat(),
            "checked_at": (datetime.now(UTC) - timedelta(minutes=31)).isoformat(),
        },
    )
    await session.flush()

    result = await check_pool_watermark(session)

    assert result["alerted"] is True, "31 minutes on a 30-minute interval, and 7h since the last"


async def test_a_zero_threshold_disables_it(session, monkeypatch) -> None:
    rec = _Recorder()
    monkeypatch.setattr("app.services.ops_alerts.notify_ops", rec)
    await _pool(session, free_phones=0)
    await settings_svc.set_value(session, "pool_low_watermark", 0)
    await session.flush()

    assert await check_pool_watermark(session) == {"skipped": "disabled"}
    assert rec.sent == []

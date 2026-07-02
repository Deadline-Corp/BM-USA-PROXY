"""Seed idempotency + correctness of the real client data."""

from __future__ import annotations

from app.models import AppSetting, Location, Tariff
from scripts.seed import seed_faq, seed_locations, seed_settings, seed_tariffs
from sqlalchemy import func, select


async def test_seed_is_idempotent(session) -> None:
    for _ in range(2):  # running twice must not duplicate
        await seed_settings(session)
        await seed_tariffs(session)
        await seed_locations(session)
        await seed_faq(session)
        await session.flush()

    tariffs = await session.scalar(select(func.count()).select_from(Tariff))
    locations = await session.scalar(select(func.count()).select_from(Location))
    assert tariffs == 5
    assert locations == 9


async def test_trial_tariff_has_one_swap(session) -> None:
    await seed_tariffs(session)
    await session.flush()
    trial = await session.scalar(select(Tariff).where(Tariff.code == "trial"))
    assert trial is not None
    assert trial.max_per_user == 1
    assert trial.max_user_swaps == 1
    assert float(trial.price_usd) == 0.0


async def test_tos_seeded_with_email_question(session) -> None:
    await seed_settings(session)
    await session.flush()
    tos = await session.scalar(select(AppSetting).where(AppSetting.key == "tos"))
    assert tos is not None
    assert tos.value["version"] == 1
    assert "Terms of Service" in tos.value["text_md"]
    questions = tos.value["questions"]
    assert [q["id"] for q in questions] == ["email"]
    assert questions[0]["required"] is True

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


async def test_a_price_the_operator_changed_survives_the_next_deploy(session) -> None:
    """The seed runs on every boot, so this is what a deploy does to the client's pricing.

    It used to overwrite every column, and the client sold Daily at $4 while this file
    said $10 — so each deploy quietly put it back to $10 and the sale price had to be
    re-entered. Plans belong to whoever edits them in the console once they exist.
    """
    await seed_tariffs(session)
    await session.flush()

    daily = await session.scalar(select(Tariff).where(Tariff.code == "daily"))
    assert daily is not None
    daily.price_usd = 4
    daily.name = "Daily (promo)"
    await session.flush()

    await seed_tariffs(session)  # the next deploy
    await session.flush()
    await session.refresh(daily)

    assert float(daily.price_usd) == 4.0
    assert daily.name == "Daily (promo)"


async def test_trial_tariff_has_one_swap(session) -> None:
    await seed_tariffs(session)
    await session.flush()
    trial = await session.scalar(select(Tariff).where(Tariff.code == "trial"))
    assert trial is not None
    assert trial.max_per_user == 1
    assert trial.max_user_swaps == 1
    assert float(trial.price_usd) == 0.0


async def test_tos_is_seeded_with_no_questions_to_answer(session) -> None:
    """Acceptance is the signature; the email box in front of it is gone.

    It was one more thing to type before buying and collected an address support never
    used — these customers are reached on Telegram. The mechanism is untouched, so an
    operator can add a question back on the Terms screen; it is only the seeded one that
    has gone.
    """
    await seed_settings(session)
    await session.flush()
    tos = await session.scalar(select(AppSetting).where(AppSetting.key == "tos"))
    assert tos is not None
    assert tos.value["version"] == 1
    assert "Terms of Service" in tos.value["text_md"]
    assert tos.value["questions"] == []

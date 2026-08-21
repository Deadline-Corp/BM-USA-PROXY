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


async def test_the_carrier_answer_reaches_a_store_that_already_has_a_faq(session) -> None:
    """The answer it fixes was given on a live system, so it has to land on a full table.

    `seed_faq` only ever fills an empty one, which is right for the app's FAQ but would have
    meant this correction never reached the store that needed it.
    """
    from app.models import FaqItem
    from scripts.seed import seed_bot_answers, seed_faq

    await seed_faq(session)
    await session.commit()
    before = int(
        await session.scalar(select(func.count()).select_from(FaqItem)) or 0
    )
    assert before > 0

    await seed_bot_answers(session)
    await session.commit()

    carrier = await session.scalar(
        select(FaqItem).where(FaqItem.question.ilike("%carriers do you work with%"))
    )
    assert carrier is not None
    assert "AT&T" in carrier.answer
    assert carrier.use_in_bot is True


async def test_seeding_again_never_rewrites_an_answer_the_operator_changed(session) -> None:
    """Same rule as the plan prices: what the console says is what ships.

    A deploy quietly restoring our wording over theirs is the bug that reset the client's
    prices twice in one day, in a different table.
    """
    from app.models import FaqItem
    from scripts.seed import seed_bot_answers

    await seed_bot_answers(session)
    await session.commit()
    row = await session.scalar(
        select(FaqItem).where(FaqItem.question.ilike("%carriers do you work with%"))
    )
    assert row is not None
    row.answer = "Verizon only for now."
    row.use_in_bot = False
    await session.commit()

    await seed_bot_answers(session)
    await session.commit()

    await session.refresh(row)
    assert row.answer == "Verizon only for now."
    assert row.use_in_bot is False
    assert (
        int(
            await session.scalar(
                select(func.count())
                .select_from(FaqItem)
                .where(FaqItem.question.ilike("%carriers do you work with%"))
            )
            or 0
        )
        == 1
    )


async def test_a_development_password_never_creates_an_admin_off_local(session, monkeypatch) -> None:
    """Found on production: the owner account authenticated with this repo's local password.

    Telegram OTP was the only thing between a publicly known credential and the console.
    Refusing to create the account is the right failure — a bootstrap admin nobody can sign
    in as is recoverable, one anybody can is not.
    """
    from pydantic import SecretStr

    from app.core.config import settings as app_settings
    from app.models import AdminUser
    from scripts.seed import seed_admin

    monkeypatch.setattr(app_settings, "env", "staging", raising=False)
    monkeypatch.setattr(app_settings, "seed_admin_password", SecretStr("dev-owner-pw"), raising=False)
    monkeypatch.setattr(app_settings, "seed_admin_email", "guard@bmusproxy.local", raising=False)

    await seed_admin(session)
    await session.flush()

    created = await session.scalar(
        select(AdminUser).where(AdminUser.email == "guard@bmusproxy.local")
    )
    assert created is None, "a known dev password must not become a production credential"


async def test_a_real_password_still_seeds_the_owner(session, monkeypatch) -> None:
    """The guard must refuse the known-weak list, not the feature."""
    from pydantic import SecretStr

    from app.core.config import settings as app_settings
    from app.models import AdminUser
    from scripts.seed import seed_admin

    monkeypatch.setattr(app_settings, "env", "staging", raising=False)
    monkeypatch.setattr(
        app_settings, "seed_admin_password", SecretStr("Xw7!qP2mZr9$Lk4vB1"), raising=False
    )
    monkeypatch.setattr(app_settings, "seed_admin_email", "real@bmusproxy.local", raising=False)

    await seed_admin(session)
    await session.flush()

    created = await session.scalar(
        select(AdminUser).where(AdminUser.email == "real@bmusproxy.local")
    )
    assert created is not None and created.role == "owner"

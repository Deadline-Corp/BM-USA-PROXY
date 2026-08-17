"""Users (Telegram customers) and admin_users (operator/owner accounts)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.models.base import Base, created_at_col, pk, updated_at_col


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = pk()
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    tg_username: Mapped[str | None] = mapped_column(Text)
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    email: Mapped[str | None] = mapped_column(CITEXT)  # from ToS form (answers.email)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")

    referral_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    referrer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    referral_bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Times somebody opened THIS person's referral link. Counted on the referrer, and
    # counted even when the visitor cannot be bound — already has a referrer, or is just
    # coming back — because that is the difference between "nobody clicks" and "they click
    # and do not sign up", which are opposite problems.
    referral_clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    source_post_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("posts.id", use_alter=True, name="fk_users_source_post_id_posts")
    )
    is_bot_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # When we last asked Telegram what this person's handle is. Not the same as last_seen_at:
    # a visit tells us what the *client* had cached in its init-data, which lags a rename by
    # however long that cache lives. NULL means never asked, and sorts first.
    handle_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operator_note: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    __table_args__ = (
        CheckConstraint("status IN ('active','banned')", name="status_valid"),
        Index(
            "ix_users_referrer",
            "referrer_user_id",
            postgresql_where="referrer_user_id IS NOT NULL",
        ),
        Index("ix_users_username", "tg_username"),
    )


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = pk()
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)  # argon2id
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="operator")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    failed_logins: Mapped[int] = mapped_column(nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Tokens issued before this are refused — see api/deps.py. Set when the password
    # changes or the account is deactivated, which is what makes either of those actually
    # end the sessions the person already has rather than only the next login.
    sessions_valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Where the login code is sent. The handle is what the owner knows and types; the
    # numeric id is the only thing a bot can actually message, and it is bound when that
    # person first opens the bot. Editing the handle clears the id — a new handle means a
    # new person, and their codes must not keep going to the old inbox.
    telegram_username: Mapped[str | None] = mapped_column(Text)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)
    # Set when the account is deleted. The row outlives the account on purpose: the audit
    # log, the client conversation and publication comments all print this person's name,
    # and those entries were written before anybody decided to remove them.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        CheckConstraint("role IN ('owner','operator')", name="role_valid"),
        # Declared here because migration 0010 creates it. Without it in the model,
        # `alembic check` reports drift and proposes dropping the index on every run —
        # the CI step that exists to catch a schema the code no longer describes was
        # failing on a schema the code simply forgot to mention.
        # It is a real guarantee, not bookkeeping: one Telegram account must not be able
        # to receive sign-in codes for two console accounts.
        Index("uq_admin_telegram_user", "telegram_user_id", unique=True),
    )

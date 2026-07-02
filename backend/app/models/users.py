"""Users (Telegram customers) and admin_users (operator/owner accounts)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, Text
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
    source_post_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("posts.id", use_alter=True, name="fk_users_source_post_id_posts")
    )
    is_bot_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
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
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        CheckConstraint("role IN ('owner','operator')", name="role_valid"),
    )

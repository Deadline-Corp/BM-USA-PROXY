"""System tables: tos_acceptances, notifications_outbox, app_settings, audit_log."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.models.base import Base, created_at_col, pk


class TosAcceptance(Base):
    """Terms of Use gate — append-only legal trail, replaces the client's Google Form."""

    __tablename__ = "tos_acceptances"

    id: Mapped[int] = pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    answers: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "version", name="user_version"),
        CheckConstraint("source IN ('bot','twa')", name="source_valid"),
    )


class NotificationOutbox(Base):
    __tablename__ = "notifications_outbox"

    id: Mapped[int] = pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    template_code: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    dedupe_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','sent','failed','blocked','skipped')", name="status_valid"
        ),
        Index(
            "uq_outbox_dedupe",
            "dedupe_key",
            unique=True,
            postgresql_where="dedupe_key IS NOT NULL",
        ),
        Index("ix_outbox_due", "status", "scheduled_at", postgresql_where="status = 'pending'"),
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict | list] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConversationMessage(Base):
    """Two-way client↔operator thread: inbound client DMs to the bot + operator replies.

    Inbound rows (``direction='in'``) are captured by the bot catch-all handler; outbound
    rows (``direction='out'``) are written when an operator messages the client from the
    admin. ``read_at`` drives the operator "unread messages" badge — set when an operator
    opens the client's dossier.
    """

    __tablename__ = "conversation_messages"

    id: Mapped[int] = pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)  # 'in' | 'out'
    body: Mapped[str] = mapped_column(Text, nullable=False)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))  # 'out' only
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)  # 'in' only
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        CheckConstraint("direction IN ('in','out')", name="direction_valid"),
        Index("ix_conv_user", "user_id", text("created_at DESC")),
        Index(
            "ix_conv_unread",
            "user_id",
            postgresql_where=text("direction = 'in' AND read_at IS NULL"),
        ),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = pk()
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (Index("ix_audit_entity", "entity", "entity_id"),)

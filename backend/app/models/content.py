"""Content & support: channels, posts, broadcasts, deliveries, faq, requests."""

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.models.base import Base, created_at_col, pk, updated_at_col


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = pk()
    tg_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = created_at_col()


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = pk()
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    media: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    deep_link_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','scheduled','posted','failed','deleted')", name="status_valid"
        ),
        Index("ix_posts_due", "status", "scheduled_at", postgresql_where="status = 'scheduled'"),
    )


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    media: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    audience_filter: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','scheduled','sending','done','failed','cancelled')",
            name="status_valid",
        ),
    )


class BroadcastDelivery(Base):
    __tablename__ = "broadcast_deliveries"

    id: Mapped[int] = pk()
    broadcast_id: Mapped[int] = mapped_column(ForeignKey("broadcasts.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("broadcast_id", "user_id", name="broadcast_user"),
        CheckConstraint(
            "status IN ('pending','sent','failed','blocked')", name="status_valid"
        ),
        Index(
            "ix_bdeliv_pending",
            "broadcast_id",
            "status",
            postgresql_where="status = 'pending'",
        ),
    )


class FaqItem(Base):
    __tablename__ = "faq_items"

    id: Mapped[int] = pk()
    category: Mapped[str] = mapped_column(Text, nullable=False, server_default="general")
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    updated_at: Mapped[datetime] = updated_at_col()


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[int] = pk()
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="new")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    __table_args__ = (
        CheckConstraint(
            "type IN ('reseller','support','refund','custom')", name="type_valid"
        ),
        CheckConstraint(
            "status IN ('new','in_progress','done','rejected')", name="status_valid"
        ),
        Index("ix_requests_board", "status", text("updated_at DESC")),
    )


class RequestComment(Base):
    __tablename__ = "request_comments"

    id: Mapped[int] = pk()
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), nullable=False)
    author_admin_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at_col()

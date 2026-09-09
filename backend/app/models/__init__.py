"""Import all models so ``Base.metadata`` is fully populated for Alembic + tests."""

from app.models.access import Access, AccessEvent, AccessVpnConfig
from app.models.base import Base
from app.models.catalog import Connection, Location, StateCity, Tariff
from app.models.commerce import Invoice, Order, PaymentEvent, Refund
from app.models.content import (
    Broadcast,
    BroadcastDelivery,
    Channel,
    FaqItem,
    Post,
    Request,
    RequestComment,
)
from app.models.onchain import ChainCursor, InvoiceStatusHistory, OnchainDepositLedger
from app.models.promo import PromoCode, PromoRedemption
from app.models.referral import Payout, ReferralLedger
from app.models.system import (
    AppSetting,
    AuditLog,
    ConversationMessage,
    MediaAsset,
    NotificationOutbox,
    TosAcceptance,
)
from app.models.users import AdminUser, User

__all__ = [
    "AccessVpnConfig",
    "Base",
    "Access",
    "AccessEvent",
    "AdminUser",
    "AppSetting",
    "AuditLog",
    "Broadcast",
    "BroadcastDelivery",
    "ChainCursor",
    "Channel",
    "Connection",
    "ConversationMessage",
    "FaqItem",
    "Invoice",
    "InvoiceStatusHistory",
    "Location",
    "StateCity",
    "MediaAsset",
    "NotificationOutbox",
    "OnchainDepositLedger",
    "Order",
    "Payout",
    "PaymentEvent",
    "Post",
    "PromoCode",
    "PromoRedemption",
    "ReferralLedger",
    "Refund",
    "Request",
    "RequestComment",
    "Tariff",
    "TosAcceptance",
    "User",
]

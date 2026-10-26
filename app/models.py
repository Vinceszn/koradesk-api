"""Ledger-first schema: money and stock only change via logged rows."""

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    whatsapp_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(32), default="pilot")
    approval_limit_ngn: Mapped[int] = mapped_column(default=80000)
    stage: Mapped[str] = mapped_column(String(32), default="onboarding", index=True)
    stage_changed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    monthly_cap: Mapped[int] = mapped_column(default=100)
    cap_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PriceListItem(Base):
    __tablename__ = "price_list_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    unit: Mapped[str] = mapped_column(String(64), default="each")
    price_ngn: Mapped[int] = mapped_column()
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_list_items.id"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    customer_name: Mapped[str] = mapped_column(String(200), default="")
    lines_json: Mapped[str] = mapped_column(Text, default="[]")
    total_ngn: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    reference: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    amount_ngn: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    amount_ngn: Mapped[int] = mapped_column()
    sender_hint: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(32), default="alert")
    status: Mapped[str] = mapped_column(String(32), default="unmatched", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    item_name: Mapped[str] = mapped_column(String(200), index=True)
    delta: Mapped[int] = mapped_column()
    reason: Mapped[str] = mapped_column(String(64), default="sale")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    decided_by: Mapped[str] = mapped_column(String(128), default="")
    escalated: Mapped[bool] = mapped_column(default=False)
    escalated_red: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MessageLog(Base):
    __tablename__ = "message_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id"), nullable=True, index=True)
    meta_message_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    direction: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(32), default="text")
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CostLedger(Base):
    __tablename__ = "cost_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id"), nullable=True, index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    meta_cost_ngn: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    ai_cost_ngn: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    messages: Mapped[int] = mapped_column(Integer, default=0)


class Conversation(Base):
    """24h billing windows per customer per number. THE cap counter."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    customer_key: Mapped[str] = mapped_column(String(64), index=True)
    window_start: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    messages: Mapped[int] = mapped_column(Integer, default=0)


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    business: Mapped[str] = mapped_column(String(200), default="")
    contact: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(64), default="whatsapp")
    plan_interest: Mapped[str] = mapped_column(String(32), default="starter")
    stage: Mapped[str] = mapped_column(String(32), default="new", index=True)
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OveragePack(Base):
    """₦5,000 per 100 conversations. Packs raise the effective cap."""

    __tablename__ = "overage_packs"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    conversations: Mapped[int] = mapped_column(default=100)
    amount_ngn: Mapped[int] = mapped_column(default=5000)
    month: Mapped[str] = mapped_column(String(7), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlanChange(Base):
    """Audit trail for plan moves. Plans change via dashboard, never by hand."""

    __tablename__ = "plan_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    from_plan: Mapped[str] = mapped_column(String(32))
    to_plan: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OpsAlert(Base):
    """Dedupe for mailed alerts. One row per (kind, shop, period)."""

    __tablename__ = "ops_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id"), nullable=True)
    period: Mapped[str] = mapped_column(String(32), index=True)
    sent_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

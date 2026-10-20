"""Commerce milestone one. Tenant consistency is enforced by composite FKs."""
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class User(Base):
    __tablename__ = "commerce_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class LoginSession(Base):
    __tablename__ = "commerce_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("commerce_users.id", ondelete="CASCADE"))
    csrf: Mapped[str] = mapped_column(String(64))
    expires: Mapped[int] = mapped_column(Integer)


class LoginAttempt(Base):
    __tablename__ = "commerce_login_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    at: Mapped[int] = mapped_column(Integer, index=True)


class Merchant(Base):
    __tablename__ = "commerce_merchants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80))
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    contact_email: Mapped[str] = mapped_column(String(254), default="", server_default="")
    phone: Mapped[str] = mapped_column(String(40), default="", server_default="")
    address: Mapped[str] = mapped_column(String(300), default="", server_default="")
    receipt_note: Mapped[str] = mapped_column(String(300), default="", server_default="")


class Membership(Base):
    __tablename__ = "commerce_memberships"
    __table_args__ = (UniqueConstraint("merchant_id", "user_id"), CheckConstraint("role IN ('owner', 'staff')"))
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("commerce_merchants.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("commerce_users.id"))
    role: Mapped[str] = mapped_column(String(16))


class Location(Base):
    __tablename__ = "commerce_locations"
    __table_args__ = (UniqueConstraint("id", "merchant_id"), UniqueConstraint("merchant_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("commerce_merchants.id"))
    name: Mapped[str] = mapped_column(String(120))


class Product(Base):
    __tablename__ = "commerce_products"
    __table_args__ = (UniqueConstraint("id", "merchant_id"), UniqueConstraint("merchant_id", "name"))
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("commerce_merchants.id"))
    name: Mapped[str] = mapped_column(String(160))


class Variant(Base):
    __tablename__ = "commerce_variants"
    __table_args__ = (
        UniqueConstraint("id", "merchant_id"), UniqueConstraint("merchant_id", "sku"),
        ForeignKeyConstraint(["product_id", "merchant_id"], ["commerce_products.id", "commerce_products.merchant_id"]),
        CheckConstraint("price_kobo >= 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("commerce_merchants.id"))
    product_id: Mapped[int] = mapped_column(Integer)
    sku: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(120), default="Standard")
    price_kobo: Mapped[int] = mapped_column(Integer)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class AccountToken(Base):
    __tablename__ = "commerce_account_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("commerce_users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(16))
    expires: Mapped[int] = mapped_column(Integer)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Customer(Base):
    __tablename__ = "commerce_customers"
    __table_args__ = (UniqueConstraint("id", "merchant_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("commerce_merchants.id"))
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    notes: Mapped[str] = mapped_column(String(500), default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Balance(Base):
    __tablename__ = "commerce_balances"
    __table_args__ = (
        UniqueConstraint("merchant_id", "location_id", "variant_id"),
        ForeignKeyConstraint(["location_id", "merchant_id"], ["commerce_locations.id", "commerce_locations.merchant_id"]),
        ForeignKeyConstraint(["variant_id", "merchant_id"], ["commerce_variants.id", "commerce_variants.merchant_id"]),
        CheckConstraint("on_hand >= 0 AND reserved >= 0 AND reserved <= on_hand"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("commerce_merchants.id"))
    location_id: Mapped[int] = mapped_column(Integer)
    variant_id: Mapped[int] = mapped_column(Integer)
    on_hand: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    counted: Mapped[bool] = mapped_column(Boolean, default=False)


class Movement(Base):
    __tablename__ = "commerce_movements"
    __table_args__ = (
        UniqueConstraint("merchant_id", "idempotency_key"),
        ForeignKeyConstraint(["location_id", "merchant_id"], ["commerce_locations.id", "commerce_locations.merchant_id"]),
        ForeignKeyConstraint(["variant_id", "merchant_id"], ["commerce_variants.id", "commerce_variants.merchant_id"]),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("commerce_merchants.id"))
    location_id: Mapped[int] = mapped_column(Integer)
    variant_id: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[int] = mapped_column(ForeignKey("commerce_users.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    at: Mapped[int] = mapped_column(Integer)


class Invitation(Base):
    __tablename__ = "commerce_invitations"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("commerce_merchants.id"))
    email: Mapped[str] = mapped_column(String(254))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[int] = mapped_column(ForeignKey("commerce_users.id"))
    expires: Mapped[int] = mapped_column(Integer)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)

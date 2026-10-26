"""Orders, immutable item snapshots and atomic stock reservations."""
from alembic import op
import sqlalchemy as sa

revision = "0005_orders_reservations"
down_revision = "0004_account_workspace"
branch_labels = depends_on = None


def upgrade():
    op.create_table("commerce_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("commerce_merchants.id"), nullable=False, index=True),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(24), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("customer_name", sa.String(120), nullable=False),
        sa.Column("customer_email", sa.String(254), nullable=False),
        sa.Column("customer_phone", sa.String(40), nullable=False),
        sa.Column("order_status", sa.String(20), nullable=False, index=True),
        sa.Column("payment_status", sa.String(24), nullable=False, index=True),
        sa.Column("fulfilment_status", sa.String(24), nullable=False, index=True),
        sa.Column("subtotal_kobo", sa.Integer(), nullable=False),
        sa.Column("total_kobo", sa.Integer(), nullable=False),
        sa.Column("reserved_until", sa.Integer(), nullable=False, index=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("commerce_users.id"), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.Column("placed_at", sa.Integer(), nullable=False),
        sa.Column("cancelled_at", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("id", "merchant_id"),
        sa.UniqueConstraint("merchant_id", "reference"),
        sa.ForeignKeyConstraint(["location_id", "merchant_id"], ["commerce_locations.id", "commerce_locations.merchant_id"]),
        sa.ForeignKeyConstraint(["customer_id", "merchant_id"], ["commerce_customers.id", "commerce_customers.merchant_id"]),
        sa.CheckConstraint("order_status IN ('draft','placed','completed','cancelled','expired')"),
        sa.CheckConstraint("payment_status IN ('unpaid','partially_paid','paid','partially_refunded','refunded')"),
        sa.CheckConstraint("fulfilment_status IN ('unfulfilled','partially_fulfilled','fulfilled','cancelled')"),
        sa.CheckConstraint("subtotal_kobo >= 0 AND total_kobo >= 0"))
    op.create_table("commerce_order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("commerce_merchants.id"), nullable=False, index=True),
        sa.Column("order_id", sa.Integer(), nullable=False, index=True),
        sa.Column("variant_id", sa.Integer(), nullable=False),
        sa.Column("product_name", sa.String(160), nullable=False),
        sa.Column("variant_label", sa.String(120), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_kobo", sa.Integer(), nullable=False),
        sa.Column("line_total_kobo", sa.Integer(), nullable=False),
        sa.UniqueConstraint("id", "merchant_id"),
        sa.UniqueConstraint("order_id", "variant_id"),
        sa.ForeignKeyConstraint(["order_id", "merchant_id"], ["commerce_orders.id", "commerce_orders.merchant_id"]),
        sa.ForeignKeyConstraint(["variant_id", "merchant_id"], ["commerce_variants.id", "commerce_variants.merchant_id"]),
        sa.CheckConstraint("quantity > 0 AND unit_price_kobo >= 0 AND line_total_kobo >= 0"))
    op.create_table("commerce_stock_reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("commerce_merchants.id"), nullable=False, index=True),
        sa.Column("order_id", sa.Integer(), nullable=False, index=True),
        sa.Column("order_item_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("variant_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, index=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("transitioned_at", sa.Integer(), nullable=False),
        sa.UniqueConstraint("id", "merchant_id"),
        sa.ForeignKeyConstraint(["order_id", "merchant_id"], ["commerce_orders.id", "commerce_orders.merchant_id"]),
        sa.ForeignKeyConstraint(["order_item_id", "merchant_id"], ["commerce_order_items.id", "commerce_order_items.merchant_id"]),
        sa.ForeignKeyConstraint(["location_id", "merchant_id"], ["commerce_locations.id", "commerce_locations.merchant_id"]),
        sa.ForeignKeyConstraint(["variant_id", "merchant_id"], ["commerce_variants.id", "commerce_variants.merchant_id"]),
        sa.CheckConstraint("quantity > 0"),
        sa.CheckConstraint("state IN ('active','released','consumed','expired')"))
    op.create_table("commerce_order_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("commerce_merchants.id"), nullable=False, index=True),
        sa.Column("order_id", sa.Integer(), nullable=False, index=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("commerce_users.id"), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("details", sa.String(300), nullable=False),
        sa.Column("at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["order_id", "merchant_id"], ["commerce_orders.id", "commerce_orders.merchant_id"]))
    op.create_table("commerce_order_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("commerce_merchants.id"), nullable=False, index=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.UniqueConstraint("merchant_id", "request_key"),
        sa.ForeignKeyConstraint(["order_id", "merchant_id"], ["commerce_orders.id", "commerce_orders.merchant_id"]))


def downgrade():
    for name in ("order_requests", "order_events", "stock_reservations", "order_items", "orders"):
        op.drop_table("commerce_" + name)

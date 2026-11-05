"""Cashier capability, cash declarations and line fulfilment progress."""
from alembic import op
import sqlalchemy as sa
revision = "0007_cash_sales"
down_revision = "0006_variant_barcodes"
branch_labels = depends_on = None

def upgrade():
    op.add_column("commerce_memberships", sa.Column("can_sell", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("commerce_order_items", sa.Column("fulfilled_quantity", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("commerce_order_items", sa.Column("cancelled_quantity", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("commerce_cash_sales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("commerce_merchants.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("amount_kobo", sa.Integer(), nullable=False),
        sa.Column("tendered_kobo", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("commerce_users.id"), nullable=False),
        sa.Column("at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["order_id","merchant_id"], ["commerce_orders.id","commerce_orders.merchant_id"]),
        sa.UniqueConstraint("order_id"), sa.CheckConstraint("amount_kobo >= 0 AND tendered_kobo >= amount_kobo"))

def downgrade():
    op.drop_table("commerce_cash_sales")
    op.drop_column("commerce_order_items", "cancelled_quantity")
    op.drop_column("commerce_order_items", "fulfilled_quantity")
    op.drop_column("commerce_memberships", "can_sell")

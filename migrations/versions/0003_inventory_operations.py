"""Inventory operations, supplier directory and stock concurrency versions."""

import sqlalchemy as sa
from alembic import op

revision = "0003_inventory_operations"
down_revision = "0002_account_catalogue"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "commerce_balances", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "commerce_balances",
        sa.Column("low_stock_threshold", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "commerce_suppliers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "merchant_id", sa.Integer(), sa.ForeignKey("commerce_merchants.id"), nullable=False
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("phone", sa.String(40), nullable=False),
        sa.Column("notes", sa.String(500), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("id", "merchant_id"),
    )
    op.create_table(
        "commerce_stock_operations",
        sa.Column(
            "movement_id", sa.Integer(), sa.ForeignKey("commerce_movements.id"), primary_key=True
        ),
        sa.Column(
            "merchant_id", sa.Integer(), sa.ForeignKey("commerce_merchants.id"), nullable=False
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("supplier_name", sa.String(120), nullable=False),
        sa.Column("unit_cost_kobo", sa.Integer(), nullable=True),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.Column(
            "reverses_id",
            sa.Integer(),
            sa.ForeignKey("commerce_movements.id"),
            nullable=True,
            unique=True,
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id", "merchant_id"],
            ["commerce_suppliers.id", "commerce_suppliers.merchant_id"],
        ),
        sa.CheckConstraint("unit_cost_kobo IS NULL OR unit_cost_kobo >= 0"),
    )


def downgrade():
    op.drop_table("commerce_stock_operations")
    op.drop_table("commerce_suppliers")
    op.drop_column("commerce_balances", "low_stock_threshold")
    op.drop_column("commerce_balances", "version")

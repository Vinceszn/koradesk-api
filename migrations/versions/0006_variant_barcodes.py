"""Add tenant-scoped variant barcode records for the POS."""
from alembic import op
import sqlalchemy as sa

revision = "0006_variant_barcodes"
down_revision = "0005_orders_reservations"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "commerce_variant_barcodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("commerce_merchants.id"), nullable=False),
        sa.Column("variant_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("symbology", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["variant_id", "merchant_id"], ["commerce_variants.id", "commerce_variants.merchant_id"]),
        sa.CheckConstraint("length(code) BETWEEN 1 AND 128"),
        sa.CheckConstraint("symbology IN ('unknown','ean8','ean13','upca','gtin14','code128')"),
    )
    active = sa.text("archived = false")
    primary = sa.text("archived = false AND is_primary = true")
    op.create_index("uq_active_barcode_merchant", "commerce_variant_barcodes", ["merchant_id", "code"],
                    unique=True, sqlite_where=active, postgresql_where=active)
    op.create_index("uq_primary_barcode_variant", "commerce_variant_barcodes", ["merchant_id", "variant_id"],
                    unique=True, sqlite_where=primary, postgresql_where=primary)


def downgrade():
    op.drop_index("uq_primary_barcode_variant", table_name="commerce_variant_barcodes")
    op.drop_index("uq_active_barcode_merchant", table_name="commerce_variant_barcodes")
    op.drop_table("commerce_variant_barcodes")

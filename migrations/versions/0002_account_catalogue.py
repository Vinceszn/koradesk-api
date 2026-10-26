"""Sprint one account, merchant and catalogue maintenance."""

import sqlalchemy as sa
from alembic import op

revision = "0002_account_catalogue"
down_revision = "0001_commerce"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "commerce_users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for name, length in [
        ("contact_email", 254),
        ("phone", 40),
        ("address", 300),
        ("receipt_note", 300),
    ]:
        op.add_column(
            "commerce_merchants",
            sa.Column(name, sa.String(length), nullable=False, server_default=""),
        )
    op.add_column(
        "commerce_variants",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "commerce_variants", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_table(
        "commerce_account_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("commerce_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("expires", sa.Integer(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "commerce_customers",
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


def downgrade():
    op.drop_table("commerce_customers")
    op.drop_table("commerce_account_tokens")
    op.drop_column("commerce_variants", "version")
    op.drop_column("commerce_variants", "archived")
    for name in ["receipt_note", "address", "phone", "contact_email"]:
        op.drop_column("commerce_merchants", name)
    op.drop_column("commerce_users", "email_verified")

"""Account profiles, preferences, session metadata and security controls."""
from alembic import op
import sqlalchemy as sa

revision = "0004_account_workspace"
down_revision = "0003_inventory_operations"
branch_labels = depends_on = None


def upgrade():
    op.add_column("commerce_users", sa.Column("created_at", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("commerce_users", sa.Column("closed", sa.Boolean(), nullable=False, server_default="0"))
    for name in ("created_at", "last_seen"):
        op.add_column("commerce_sessions", sa.Column(name, sa.Integer(), nullable=False, server_default="0"))
    op.add_column("commerce_sessions", sa.Column("device", sa.String(160), nullable=False, server_default="Unknown device"))
    op.create_table("commerce_account_profiles",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("commerce_users.id"), primary_key=True),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("phone", sa.String(40), nullable=False),
        sa.Column("avatar", sa.LargeBinary(), nullable=True),
        sa.Column("preferences", sa.Text(), nullable=False),
        sa.Column("totp_secret", sa.Text(), nullable=False),
        sa.Column("totp_pending", sa.Text(), nullable=False),
        sa.Column("totp_pending_expires", sa.Integer(), nullable=False),
        sa.Column("totp_last_step", sa.Integer(), nullable=False))
    op.create_table("commerce_security_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("commerce_users.id"), nullable=False, index=True),
        sa.Column("action", sa.String(160), nullable=False),
        sa.Column("at", sa.Integer(), nullable=False),
        sa.Column("device", sa.String(160), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False))
    op.create_table("commerce_email_changes",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("commerce_users.id"), nullable=False, index=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("previous_email", sa.String(254), nullable=False),
        sa.Column("expires", sa.Integer(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False))
    op.create_table("commerce_recovery_codes",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("commerce_users.id"), nullable=False, index=True),
        sa.Column("used", sa.Boolean(), nullable=False))
    op.create_table("commerce_business_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("commerce_users.id"), nullable=False),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("commerce_merchants.id"), nullable=False),
        sa.Column("low_stock", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("user_id", "merchant_id"))


def downgrade():
    for name in ("business_notifications", "recovery_codes", "email_changes", "security_events", "account_profiles"):
        op.drop_table("commerce_" + name)
    for name in ("device", "last_seen", "created_at"):
        op.drop_column("commerce_sessions", name)
    op.drop_column("commerce_users", "closed")
    op.drop_column("commerce_users", "created_at")

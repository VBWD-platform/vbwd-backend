"""Create the core ``vbwd_api_key`` table (S52).

Generic, domain-neutral auth-mechanism table: a user holds scoped,
IP-restricted API keys. Only the sha256 hash + a short display prefix are
stored — never the plaintext token.

A CORE table, so this migration anchors only on the current core head
(``20260608_inv_admin_idx``) and resolves standalone (no plugin present).

Revision ID: 20260606_1000_create_api_key
Revises: 20260608_inv_admin_idx
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "20260606_1000_create_api_key"
down_revision = "20260608_inv_admin_idx"
branch_labels = None
depends_on = None

TABLE = "vbwd_api_key"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("vbwd_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("scopes", JSONB(), nullable=False),
        sa.Column("ip_whitelist", JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_vbwd_api_key_user_id", TABLE, ["user_id"])
    op.create_index("ix_vbwd_api_key_key_hash", TABLE, ["key_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_vbwd_api_key_key_hash", table_name=TABLE)
    op.drop_index("ix_vbwd_api_key_user_id", table_name=TABLE)
    op.drop_table(TABLE)

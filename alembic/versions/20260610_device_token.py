"""Create the core ``vbwd_device_token`` table (S66).

Generic, domain-neutral push-notification mechanism table: a user's device
registers an opaque platform token for a named client app. Unique on
``token`` (register is an upsert — latest user wins); composite index on
``(user_id, app, revoked_at)`` for the active-token dispatch lookup.

A CORE table, so this migration anchors only on the current core head
(``20260606_1000_create_api_key``) and resolves standalone (no plugin
present).

Revision ID: 20260610_device_token
Revises: 20260606_1000_create_api_key
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "20260610_device_token"
down_revision = "20260606_1000_create_api_key"
branch_labels = None
depends_on = None

TABLE = "vbwd_device_token"


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
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("bundle_id", sa.String(length=255), nullable=False),
        sa.Column("app", sa.String(length=64), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_vbwd_device_token_token", TABLE, ["token"], unique=True)
    op.create_index(
        "ix_vbwd_device_token_user_app_revoked",
        TABLE,
        ["user_id", "app", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_vbwd_device_token_user_app_revoked", table_name=TABLE)
    op.drop_index("ix_vbwd_device_token_token", table_name=TABLE)
    op.drop_table(TABLE)

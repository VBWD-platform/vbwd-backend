"""Create the core outbound-webhook tables.

Two pure CORE tables — ``vbwd_webhook`` (admin-registered subscriptions) and
``vbwd_webhook_delivery`` (per-event delivery attempts) — with NO plugin FK, so
the migration resolves/runs standalone and core stays resolvable on its own
(project_migration_graph_fragmentation). The outbound webhook system relays
event-bus events to subscriber URLs and names no plugin.

Revision ID: 20260619_1000_outbound_webhooks
Revises: 20260616_1600_rename_al_model
Create Date: 2026-06-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "20260619_1000_outbound_webhooks"
down_revision = "20260616_1600_rename_al_model"
branch_labels = None
depends_on = None

SUBSCRIPTION_TABLE = "vbwd_webhook"
DELIVERY_TABLE = "vbwd_webhook_delivery"


def upgrade() -> None:
    op.create_table(
        SUBSCRIPTION_TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("secret", sa.String(length=128), nullable=False),
        sa.Column(
            "event_types",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(), nullable=True),
        sa.Column(
            "consecutive_failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        DELIVERY_TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "webhook_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{SUBSCRIPTION_TABLE}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column(
            "event_payload",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("signature", sa.String(length=128), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(f"ix_{DELIVERY_TABLE}_webhook_id", DELIVERY_TABLE, ["webhook_id"])
    op.create_index(
        f"ix_{DELIVERY_TABLE}_next_attempt_at", DELIVERY_TABLE, ["next_attempt_at"]
    )


def downgrade() -> None:
    op.drop_index(f"ix_{DELIVERY_TABLE}_next_attempt_at", table_name=DELIVERY_TABLE)
    op.drop_index(f"ix_{DELIVERY_TABLE}_webhook_id", table_name=DELIVERY_TABLE)
    op.drop_table(DELIVERY_TABLE)
    op.drop_table(SUBSCRIPTION_TABLE)

"""Add payment_intent_id column to user_invoice.

Revision ID: 20260323_payment_intent
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa

revision = "20260323_payment_intent"
down_revision = None
branch_labels = ("payment_intent",)
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("user_invoice")]
    if "payment_intent_id" not in columns:
        op.add_column(
            "user_invoice",
            sa.Column("payment_intent_id", sa.String(255), nullable=True, index=True),
        )


def downgrade() -> None:
    op.drop_column("user_invoice", "payment_intent_id")

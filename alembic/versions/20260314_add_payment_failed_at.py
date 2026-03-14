"""add_payment_failed_at_to_subscription

Revision ID: f2g3h4i5j6k7
Revises: e1f2g3h4i5j6
Create Date: 2026-03-14 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2g3h4i5j6k7"
down_revision: Union[str, None] = "e1f2g3h4i5j6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscription",
        sa.Column("payment_failed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscription", "payment_failed_at")

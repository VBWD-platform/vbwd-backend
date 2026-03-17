"""add_subscription_to_tokentransactiontype_enum

Revision ID: 9f128e1f428c
Revises: 20260215_nullable_tarif_plan
Create Date: 2026-02-23 07:18:41.274947+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f128e1f428c'
down_revision: Union[str, None] = '20260215_nullable_tarif_plan'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE tokentransactiontype ADD VALUE IF NOT EXISTS 'SUBSCRIPTION'")


def downgrade() -> None:
    # PostgreSQL does not support removing values from enum types
    pass

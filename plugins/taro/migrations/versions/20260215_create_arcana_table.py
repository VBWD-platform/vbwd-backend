"""Create arcana table for Taro plugin.

Revision ID: 20260215_arcana
Revises: 20260215_nullable_tarif_plan
Create Date: 2026-02-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ENUM

# revision identifiers, used by Alembic.
revision: str = "20260215_arcana"
down_revision: Union[str, None] = "20260215_nullable_tarif_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create arcana table."""
    # Create ArcanaType enum
    arcanatype_enum = ENUM(
        "MAJOR_ARCANA",
        "CUPS",
        "WANDS",
        "SWORDS",
        "PENTACLES",
        name="arcanatype",
        create_type=True,
    )

    op.create_table(
        "arcana",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "number", sa.Integer(), nullable=True, index=True
        ),  # 0-21 for Major Arcana
        sa.Column("name", sa.String(length=255), nullable=False, index=True),
        sa.Column(
            "suit", sa.String(length=50), nullable=True, index=True
        ),  # CUPS, WANDS, SWORDS, PENTACLES
        sa.Column(
            "rank", sa.String(length=50), nullable=True, index=True
        ),  # ACE, TWO, ..., KING
        sa.Column(
            "arcana_type",
            arcanatype_enum,
            nullable=False,
            index=True,
            server_default="MAJOR_ARCANA",
        ),
        sa.Column("upright_meaning", sa.Text(), nullable=False),
        sa.Column("reversed_meaning", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create composite unique constraint for minor arcana (suit + rank)
    # For Major Arcana, number is unique; for Minor, suit+rank is unique
    op.create_unique_constraint(
        "uq_arcana_number_suit_rank",
        "arcana",
        ["number", "suit", "rank"],
    )


def downgrade() -> None:
    """Drop arcana table and enum."""
    op.drop_constraint("uq_arcana_number_suit_rank", "arcana", type_="unique")
    op.drop_table("arcana")

    # Drop enum
    op.execute("DROP TYPE IF EXISTS arcanatype")

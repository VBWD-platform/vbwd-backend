"""Create taro_session and taro_card_draw tables.

Revision ID: 20260215_taro_session_card_draw
Revises: 20260215_arcana
Create Date: 2026-02-15 12:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ENUM

# revision identifiers, used by Alembic.
revision: str = "20260215_taro_session_card_draw"
down_revision: Union[str, None] = "20260215_arcana"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create taro_session and taro_card_draw tables."""
    # Create TaroSessionStatus enum
    tarosessionstatus_enum = ENUM(
        "ACTIVE",
        "EXPIRED",
        "CLOSED",
        name="tarosessionstatus",
        create_type=True,
    )

    # Create CardPosition enum
    cardposition_enum = ENUM(
        "PAST",
        "PRESENT",
        "FUTURE",
        name="cardposition",
        create_type=True,
    )

    # Create CardOrientation enum
    cardorientation_enum = ENUM(
        "UPRIGHT",
        "REVERSED",
        name="cardorientation",
        create_type=True,
    )

    # Create taro_session table
    op.create_table(
        "taro_session",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "status",
            tarosessionstatus_enum,
            nullable=False,
            index=True,
            server_default="ACTIVE",
        ),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("spread_id", sa.String(length=50), nullable=False, index=True),
        sa.Column("tokens_consumed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("follow_up_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_follow_ups", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create taro_card_draw table
    op.create_table(
        "taro_card_draw",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("arcana_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("position", cardposition_enum, nullable=False, index=True),
        sa.Column("orientation", cardorientation_enum, nullable=False),
        sa.Column("ai_interpretation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["taro_session.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["arcana_id"], ["arcana.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create unique constraint: one card per session per position
    op.create_unique_constraint(
        "uq_taro_card_draw_session_position",
        "taro_card_draw",
        ["session_id", "position"],
    )


def downgrade() -> None:
    """Drop taro_session and taro_card_draw tables and enums."""
    # Drop taro_card_draw
    op.drop_constraint(
        "uq_taro_card_draw_session_position", "taro_card_draw", type_="unique"
    )
    op.drop_table("taro_card_draw")

    # Drop taro_session
    op.drop_table("taro_session")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS cardorientation")
    op.execute("DROP TYPE IF EXISTS cardposition")
    op.execute("DROP TYPE IF EXISTS tarosessionstatus")

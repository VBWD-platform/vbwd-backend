"""Add ``state`` (state/region) to ``vbwd_user_details``.

A CORE migration: it anchors on the current core user-chain head
(``20260711_1000_user_fk_ondelete_cascade``) and resolves standalone — no
plugin is involved. The column stores the state / region / province of the
user's address so the profile and billing-address forms can round-trip it
alongside ``postal_code``.

Additive and nullable: existing rows take ``NULL``.

Revision ID: 20260825_1000_user_details_state
Revises: 20260711_1000_user_fk_ondelete_cascade
Create Date: 2026-08-25
"""
import sqlalchemy as sa
from alembic import op


revision = "20260825_1000_user_details_state"
down_revision = "20260711_1000_user_fk_ondelete_cascade"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "vbwd_user_details",
        sa.Column("state", sa.String(length=100), nullable=True),
    )


def downgrade():
    op.drop_column("vbwd_user_details", "state")

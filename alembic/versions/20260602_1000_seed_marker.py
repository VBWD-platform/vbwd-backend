"""Create the core ``vbwd_plugin_seed_marker`` table (S30).

One row per plugin that ``flask seed`` has successfully populated. Used only
by the debug-only ``/api/v1/_seed_status`` load-test affordance — not a
production data path. A CORE table, so this migration anchors only on the
core head (``20260526_2200_md_jsonb``) and resolves standalone.

Revision ID: 20260602_1000_seed_marker
Revises: 20260526_2200_md_jsonb
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa


revision = "20260602_1000_seed_marker"
down_revision = "20260526_2200_md_jsonb"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vbwd_plugin_seed_marker",
        sa.Column("plugin_name", sa.String(length=255), primary_key=True),
        sa.Column("populated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("vbwd_plugin_seed_marker")

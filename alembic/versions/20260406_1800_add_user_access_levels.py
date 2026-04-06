"""Add user access level tables (Sprint 17a).

These tables were added to the consolidated vbwd_001 migration but not
applied to databases that were already past that revision.

Revision ID: 20260406_1800
Revises: 20260404_1500
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20260406_1800"
down_revision = "20260404_1500"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vbwd_user_access_level",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("linked_plan_slug", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vbwd_user_access_level_name",
        "vbwd_user_access_level",
        ["name"],
        unique=True,
    )
    op.create_index(
        "ix_vbwd_user_access_level_slug",
        "vbwd_user_access_level",
        ["slug"],
        unique=True,
    )
    op.create_index(
        "ix_vbwd_user_access_level_linked_plan_slug",
        "vbwd_user_access_level",
        ["linked_plan_slug"],
        unique=False,
    )

    op.create_table(
        "vbwd_user_access_level_permissions",
        sa.Column("user_access_level_id", UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_access_level_id"], ["vbwd_user_access_level.id"]
        ),
        sa.ForeignKeyConstraint(["permission_id"], ["vbwd_permission.id"]),
        sa.PrimaryKeyConstraint("user_access_level_id", "permission_id"),
    )

    op.create_table(
        "vbwd_user_user_access_levels",
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_access_level_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["vbwd_user.id"]),
        sa.ForeignKeyConstraint(
            ["user_access_level_id"], ["vbwd_user_access_level.id"]
        ),
        sa.PrimaryKeyConstraint("user_id", "user_access_level_id"),
    )


def downgrade():
    op.drop_table("vbwd_user_user_access_levels")
    op.drop_table("vbwd_user_access_level_permissions")
    op.drop_index(
        "ix_vbwd_user_access_level_linked_plan_slug",
        table_name="vbwd_user_access_level",
    )
    op.drop_index(
        "ix_vbwd_user_access_level_slug",
        table_name="vbwd_user_access_level",
    )
    op.drop_index(
        "ix_vbwd_user_access_level_name",
        table_name="vbwd_user_access_level",
    )
    op.drop_table("vbwd_user_access_level")

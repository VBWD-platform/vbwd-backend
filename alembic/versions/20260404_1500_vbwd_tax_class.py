"""Add vbwd_tax_class table and tax_class_id FK to vbwd_tax.

Revision ID: 20260404_1500
Revises: 20260403_1612
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20260404_1500"
down_revision = "vbwd_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vbwd_tax_class",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "code", sa.String(length=50), nullable=False
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "default_rate",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_vbwd_tax_class_code"),
        "vbwd_tax_class",
        ["code"],
        unique=True,
    )

    op.add_column(
        "vbwd_tax",
        sa.Column(
            "tax_class_id", UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_vbwd_tax_tax_class_id",
        "vbwd_tax",
        "vbwd_tax_class",
        ["tax_class_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_vbwd_tax_tax_class_id"),
        "vbwd_tax",
        ["tax_class_id"],
    )


def downgrade():
    op.drop_index(
        op.f("ix_vbwd_tax_tax_class_id"), table_name="vbwd_tax"
    )
    op.drop_constraint(
        "fk_vbwd_tax_tax_class_id",
        "vbwd_tax",
        type_="foreignkey",
    )
    op.drop_column("vbwd_tax", "tax_class_id")
    op.drop_index(
        op.f("ix_vbwd_tax_class_code"),
        table_name="vbwd_tax_class",
    )
    op.drop_table("vbwd_tax_class")

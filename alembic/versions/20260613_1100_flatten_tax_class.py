"""Flatten ``vbwd_tax_class`` into a denormalized ``tax_class`` label (S72.3).

A CORE migration: it anchors only on the prior core head
(``20260613_1000_curr_flags``) and resolves standalone — no plugin is
involved. Tax is core vocabulary.

The team confirmed the "entity → specific taxes" model (S72.3): nothing reads
the tax *class* for pricing or assignment (every entity links a concrete
``Tax`` by ``tax_id``), so the separate ``vbwd_tax_class`` model is unused for
behaviour. This collapses it to a denormalized ``tax_class`` string column on
``vbwd_tax``, mirroring the existing legacy ``shop_product.tax_class`` string.

Upgrade:
- adds nullable ``tax_class VARCHAR(50)`` to ``vbwd_tax``;
- data-migrates: for each tax with a ``tax_class_id``, sets ``tax_class`` to
  the referenced ``vbwd_tax_class.code``;
- drops ``vbwd_tax.tax_class_id``;
- drops the ``vbwd_tax_class`` table.

Downgrade is best-effort: it recreates ``vbwd_tax_class``, re-adds
``tax_class_id`` nullable, and drops the ``tax_class`` column. The original
class rows and the per-tax class links are NOT restored (the flatten discards
the class identity beyond its code string) — documented as lossy.

Revision ID: 20260613_1100_flatten_tax_cls
Revises: 20260613_1000_curr_flags
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from alembic import op


revision = "20260613_1100_flatten_tax_cls"
down_revision = "20260613_1000_curr_flags"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "vbwd_tax",
        sa.Column("tax_class", sa.String(length=50), nullable=True),
    )
    # Data-migrate: carry the referenced class code into the new label column.
    op.execute(
        "UPDATE vbwd_tax "
        "SET tax_class = vbwd_tax_class.code "
        "FROM vbwd_tax_class "
        "WHERE vbwd_tax.tax_class_id = vbwd_tax_class.id"
    )
    op.drop_column("vbwd_tax", "tax_class_id")
    op.drop_table("vbwd_tax_class")


def downgrade():
    op.create_table(
        "vbwd_tax_class",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_rate", sa.Numeric(5, 2), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(
        "ix_vbwd_tax_class_code", "vbwd_tax_class", ["code"], unique=True
    )
    op.add_column(
        "vbwd_tax",
        sa.Column(
            "tax_class_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "vbwd_tax_tax_class_id_fkey",
        "vbwd_tax",
        "vbwd_tax_class",
        ["tax_class_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_vbwd_tax_tax_class_id", "vbwd_tax", ["tax_class_id"]
    )
    op.drop_column("vbwd_tax", "tax_class")

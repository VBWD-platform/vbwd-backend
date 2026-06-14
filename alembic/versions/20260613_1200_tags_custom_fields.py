"""Create the core tags & custom-fields tables (S77).

Four core-owned, polymorphic tables keyed by ``(entity_type, entity_id)``:

  * ``vbwd_tag``               — the single tag catalog (slug globally unique).
  * ``vbwd_entity_tag``        — M2M link (composite PK + reverse index, D6).
  * ``vbwd_custom_field_def``  — typed field definitions (unique per entity_type).
  * ``vbwd_custom_field_value``— EAV values (composite PK = the only access path).

A CORE migration → it must resolve/run standalone (plugin-free). It also
**merges the two existing core heads** (``20260611_1000_user_groups`` and
``20260613_1100_drop_price``) into a single linear head so core stays
resolvable on its own.

Revision ID: 20260613_1200_tags_cf
Revises: 20260611_1000_user_groups, 20260613_1100_drop_price
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "20260613_1200_tags_cf"
down_revision = ("20260611_1000_user_groups", "20260613_1100_drop_price")
branch_labels = None
depends_on = None

TAG = "vbwd_tag"
ENTITY_TAG = "vbwd_entity_tag"
CF_DEF = "vbwd_custom_field_def"
CF_VALUE = "vbwd_custom_field_value"


def upgrade() -> None:
    op.create_table(
        TAG,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("parent_entity_type", sa.String(length=64), nullable=True),
        sa.Column("meta_data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_vbwd_tag_slug", TAG, ["slug"], unique=True)

    op.create_table(
        ENTITY_TAG,
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tag_slug", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["tag_slug"], [f"{TAG}.slug"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("entity_type", "entity_id", "tag_slug"),
    )
    op.create_index(
        "ix_vbwd_entity_tag_reverse",
        ENTITY_TAG,
        ["tag_slug", "entity_type", "entity_id"],
    )

    op.create_table(
        CF_DEF,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("options", JSONB(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "entity_type", "key", name="uq_vbwd_custom_field_def_entity_key"
        ),
    )
    op.create_index("ix_vbwd_custom_field_def_entity_type", CF_DEF, ["entity_type"])

    op.create_table(
        CF_VALUE,
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("field_key", sa.String(length=255), nullable=False),
        sa.Column("value", JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("entity_type", "entity_id", "field_key"),
    )


def downgrade() -> None:
    op.drop_table(CF_VALUE)
    op.drop_index("ix_vbwd_custom_field_def_entity_type", table_name=CF_DEF)
    op.drop_table(CF_DEF)
    op.drop_index("ix_vbwd_entity_tag_reverse", table_name=ENTITY_TAG)
    op.drop_table(ENTITY_TAG)
    op.drop_index("ix_vbwd_tag_slug", table_name=TAG)
    op.drop_table(TAG)

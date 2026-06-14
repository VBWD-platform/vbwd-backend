"""S73 — User Groups (core entity) + slug-keyed membership.

Creates two CORE tables:

* ``vbwd_user_groups`` — the group catalog (slug unique + indexed, name, lang,
  parent_group self-ref by slug, BaseModel id/timestamps/version).
* ``vbwd_user_group_rel`` — the user<->group M2M, keyed by ``group_slug`` with
  ON DELETE CASCADE on both FKs (deleting a user or a group prunes its
  membership rows).

Core migration: resolves standalone (anchors on the prior core head). No data
change. Reversible (validated up -> down -> up).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# The current single core leaf at S73 time. (The spec named the older head
# ``20260608_inv_admin_idx``; the core graph has since advanced — see report.)
revision = "20260611_1000_user_groups"
down_revision = "20260613_1100_flatten_tax_cls"
branch_labels = None
depends_on = None

GROUPS_TABLE = "vbwd_user_groups"
REL_TABLE = "vbwd_user_group_rel"


def upgrade() -> None:
    op.create_table(
        GROUPS_TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=True),
        sa.Column("parent_group", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("slug", name="uq_vbwd_user_groups_slug"),
    )
    op.create_index("ix_vbwd_user_groups_slug", GROUPS_TABLE, ["slug"], unique=True)

    op.create_table(
        REL_TABLE,
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("group_slug", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["vbwd_user.id"],
            ondelete="CASCADE",
            name="fk_vbwd_user_group_rel_user_id",
        ),
        sa.ForeignKeyConstraint(
            ["group_slug"],
            [f"{GROUPS_TABLE}.slug"],
            ondelete="CASCADE",
            name="fk_vbwd_user_group_rel_group_slug",
        ),
        sa.PrimaryKeyConstraint("user_id", "group_slug"),
    )


def downgrade() -> None:
    op.drop_table(REL_TABLE)
    op.drop_index("ix_vbwd_user_groups_slug", table_name=GROUPS_TABLE)
    op.drop_table(GROUPS_TABLE)

"""S85.1a — drop the dead persisted ``Price`` table (``vbwd_price``).

The persisted ``Price`` model is dead — nothing reads a ``vbwd_price`` row at
runtime (S85.0 introduced the computed ``Price`` value object as the single
``Price``). This CORE migration drops the ``vbwd_price`` table.

It resolves plugin-free: it anchors on the core chain's own prior head and
declares ``depends_on = None`` (no cross-plugin coupling), so it runs on a
core-only install where no plugin FK references ``vbwd_price``. On a full
install the subscription ``20260613_sub_drop_price_id`` migration removes the
``subscription_tarif_plan.price_id`` FK; this migration additionally drops, by
catalog lookup (never naming a plugin table), any FK still referencing
``vbwd_price`` so the table-drop is safe regardless of migration ordering.

``downgrade`` recreates the bare ``vbwd_price`` table mirroring its original
columns (including the ``vbwd_currency`` FK) but does NOT re-add the cross-plugin
``subscription_tarif_plan`` FK — that re-add lives in the subscription
migration's own ``downgrade``.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "20260613_1100_drop_price"
down_revision = "20260613_1000_curr_flags"
branch_labels = None
depends_on = None

TABLE = "vbwd_price"
CURRENCY_INDEX_NAME = "ix_vbwd_price_currency_id"


def _drop_referencing_foreign_keys() -> None:
    """Drop any FK constraints that still reference ``vbwd_price``.

    Discovered from the catalog (no plugin table name is hardcoded — keeps this
    core migration agnostic). A no-op on a core-only install where nothing
    references the table.
    """
    bind = op.get_bind()
    referencing = bind.execute(
        text(
            "SELECT conrelid::regclass::text AS table_name, conname "
            "FROM pg_constraint "
            "WHERE contype = 'f' AND confrelid = cast(:table AS regclass)"
        ),
        {"table": TABLE},
    ).fetchall()
    for table_name, constraint_name in referencing:
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")


def upgrade() -> None:
    _drop_referencing_foreign_keys()
    op.drop_index(CURRENCY_INDEX_NAME, table_name=TABLE)
    op.drop_table("vbwd_price")


def downgrade() -> None:
    op.create_table(
        "vbwd_price",
        sa.Column("price_float", sa.Float(), nullable=False),
        sa.Column("price_decimal", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency_id", sa.UUID(), nullable=False),
        sa.Column("taxes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("gross_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("net_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["currency_id"], ["vbwd_currency.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(CURRENCY_INDEX_NAME, TABLE, ["currency_id"], unique=False)

"""S85.1 — core token-bundle price storage migration + bundle↔tax join (D4/D6).

Widens the core token-bundle money columns from ``Numeric(10, 2)`` to
``double precision`` (``db.Float``) — prices are full precision and never
rounded in code (D4):

* ``vbwd_token_bundle.price``
* ``vbwd_token_bundle_purchase.price``

Creates ``token_bundle_tax`` (D6), a CORE↔CORE M2M join between
``vbwd_token_bundle`` and the CORE tax catalog ``vbwd_tax`` (both core — no
plugin coupling, the agnosticism oracle stays green), mirroring the S72.3
join-table shape: the ``tax_id`` FK is ``ON DELETE RESTRICT`` (a clean DB block,
never a silent cascade) and ``bundle_id`` is ``ON DELETE CASCADE``.

Token bundles carry no ``currency`` column (they already use the system default
currency), so nothing is dropped here. Anchors on the core chain's own current
head (``20260613_1200_tags_cf``, the merge of the user-groups + vbwd_price-drop
branches) and declares no cross-plugin coupling so it resolves on a core-only
install. ``downgrade`` drops the join table and re-narrows the prices.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260613_1200_tb_price_float"
down_revision = "20260613_1200_tags_cf"
branch_labels = None
depends_on = None

BUNDLE_TABLE = "vbwd_token_bundle"
PURCHASE_TABLE = "vbwd_token_bundle_purchase"
BUNDLE_TAX_TABLE = "token_bundle_tax"


def upgrade() -> None:
    op.alter_column(
        BUNDLE_TABLE,
        "price",
        type_=sa.Float(),
        existing_type=sa.Numeric(10, 2),
        existing_nullable=False,
        postgresql_using="price::double precision",
    )
    op.alter_column(
        PURCHASE_TABLE,
        "price",
        type_=sa.Float(),
        existing_type=sa.Numeric(10, 2),
        existing_nullable=False,
        postgresql_using="price::double precision",
    )

    op.create_table(
        BUNDLE_TAX_TABLE,
        sa.Column(
            "bundle_id",
            sa.UUID(),
            sa.ForeignKey("vbwd_token_bundle.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tax_id",
            sa.UUID(),
            sa.ForeignKey("vbwd_tax.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table(BUNDLE_TAX_TABLE)

    op.alter_column(
        PURCHASE_TABLE,
        "price",
        type_=sa.Numeric(10, 2),
        existing_type=sa.Float(),
        existing_nullable=False,
        postgresql_using="price::numeric(10,2)",
    )
    op.alter_column(
        BUNDLE_TABLE,
        "price",
        type_=sa.Numeric(10, 2),
        existing_type=sa.Float(),
        existing_nullable=False,
        postgresql_using="price::numeric(10,2)",
    )

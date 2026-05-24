"""Drop subscription/plan FK columns from the core invoice (Sprint 11 / S4).

Core `vbwd_user_invoice` no longer carries `subscription_id` / `tarif_plan_id`.
The subscription↔invoice link now lives in the invoice's SUBSCRIPTION line
item (item_id == subscription id), so core holds no FK into the subscription
plugin's tables.

This is a CORE migration (a core table changes), so it always runs — even on a
subscription-free deploy where those dangling FK columns must not linger.

Upgrade is data-safe: before dropping the columns, any legacy invoice that has
`subscription_id` set but no SUBSCRIPTION line item is given one, so the link is
preserved. Downgrade is reversible: it re-adds the columns + FKs and backfills
them from the SUBSCRIPTION line item (and the subscription's plan).

Revision ID: 20260525_1000_inv_drop_sub_fk
Revises: 20260523_1000_sub_baseline
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "20260525_1000_inv_drop_sub_fk"
down_revision = "20260523_1000_sub_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Backfill: legacy invoices linked only by the column get a SUBSCRIPTION
    #    line item so the link survives the column drop.
    conn.execute(
        sa.text(
            """
            INSERT INTO vbwd_invoice_line_item
                (id, invoice_id, item_type, item_id, description, quantity,
                 unit_price, total_price, metadata, created_at, updated_at,
                 version)
            SELECT gen_random_uuid(), inv.id, 'SUBSCRIPTION'::lineitemtype,
                   inv.subscription_id, 'Subscription', 1, inv.amount,
                   inv.amount, '{}'::json, now(), now(), 0
              FROM vbwd_user_invoice AS inv
             WHERE inv.subscription_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1
                     FROM vbwd_invoice_line_item AS li
                    WHERE li.invoice_id = inv.id
                      AND li.item_type = 'SUBSCRIPTION'::lineitemtype
               )
            """
        )
    )

    # 2. Drop the FK constraints, then the columns.
    op.drop_constraint(
        "vbwd_user_invoice_subscription_id_fkey",
        "vbwd_user_invoice",
        type_="foreignkey",
    )
    op.drop_constraint(
        "vbwd_user_invoice_tarif_plan_id_fkey",
        "vbwd_user_invoice",
        type_="foreignkey",
    )
    op.drop_column("vbwd_user_invoice", "subscription_id")
    op.drop_column("vbwd_user_invoice", "tarif_plan_id")


def downgrade() -> None:
    conn = op.get_bind()

    # 1. Re-add the columns + FK constraints (nullable, as before).
    op.add_column(
        "vbwd_user_invoice",
        sa.Column("tarif_plan_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "vbwd_user_invoice",
        sa.Column("subscription_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "vbwd_user_invoice_tarif_plan_id_fkey",
        "vbwd_user_invoice",
        "vbwd_tarif_plan",
        ["tarif_plan_id"],
        ["id"],
    )
    op.create_foreign_key(
        "vbwd_user_invoice_subscription_id_fkey",
        "vbwd_user_invoice",
        "vbwd_subscription",
        ["subscription_id"],
        ["id"],
    )

    # 2. Backfill the columns from the SUBSCRIPTION line item + its plan. Only
    #    line items whose item_id is a real subscription are restored — the FK
    #    forbids dangling references, and this keeps the downgrade safe against
    #    any stray line item that does not point at a live subscription.
    conn.execute(
        sa.text(
            """
            UPDATE vbwd_user_invoice AS inv
               SET subscription_id = li.item_id
              FROM vbwd_invoice_line_item AS li
             WHERE li.invoice_id = inv.id
               AND li.item_type = 'SUBSCRIPTION'::lineitemtype
               AND EXISTS (
                   SELECT 1 FROM vbwd_subscription AS sub
                    WHERE sub.id = li.item_id
               )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE vbwd_user_invoice AS inv
               SET tarif_plan_id = sub.tarif_plan_id
              FROM vbwd_subscription AS sub
             WHERE inv.subscription_id = sub.id
            """
        )
    )

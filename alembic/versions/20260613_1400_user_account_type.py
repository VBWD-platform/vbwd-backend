"""Add ``account_type`` to ``vbwd_user_details`` (S74).

A CORE migration: it anchors only on the current core head
(``20260613_1300_add_guest_role``) and resolves standalone — no plugin is
involved. The column declares whether a user account is a private person or
a business, which drives invoice billing identity and is reused by the shop.

Additive and backfill-safe: ``account_type`` is ``NOT NULL`` with a
``server_default`` of ``'private'``, so existing rows take the default. The
allowed values (``'private'``, ``'business'``) are enforced at the
application layer (``vbwd.models.enums.AccountType``); the column itself is a
plain ``String(16)`` (no Postgres enum type).

Revision ID: 20260613_1400_user_account_type
Revises: 20260613_1300_add_guest_role
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from alembic import op


revision = "20260613_1400_user_account_type"
down_revision = "20260613_1300_add_guest_role"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "vbwd_user_details",
        sa.Column(
            "account_type",
            sa.String(length=16),
            nullable=False,
            server_default="private",
        ),
    )


def downgrade():
    op.drop_column("vbwd_user_details", "account_type")

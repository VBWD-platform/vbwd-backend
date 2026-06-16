"""Create the core ``vbwd_llm_connection`` table (S97.1).

A pure CORE table (the admin-managed LLM Connection registry) with NO plugin
FK, so it resolves/runs standalone — core stays resolvable on its own
(project_migration_graph_fragmentation). ``api_key`` is stored as ``Text``
(the :class:`~vbwd.utils.crypto.EncryptedString` column type persists Fernet
ciphertext as Text), encrypted by the application layer at rest.

Revision ID: 20260615_1100_llm_connection
Revises: 20260615_1000_referral_commission_tx
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "20260615_1100_llm_connection"
down_revision = "20260615_1000_referral_commission_tx"
branch_labels = None
depends_on = None

TABLE = "vbwd_llm_connection"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("connection_name", sa.String(length=200), nullable=False),
        sa.Column(
            "api_endpoint",
            sa.String(length=500),
            nullable=False,
            server_default="",
        ),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("timeout", sa.Integer(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("last_active_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_unique_constraint(f"uq_{TABLE}_slug", TABLE, ["slug"])
    op.create_index(f"ix_{TABLE}_slug", TABLE, ["slug"])


def downgrade() -> None:
    op.drop_index(f"ix_{TABLE}_slug", table_name=TABLE)
    op.drop_constraint(f"uq_{TABLE}_slug", TABLE, type_="unique")
    op.drop_table(TABLE)

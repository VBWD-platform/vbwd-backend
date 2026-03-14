"""create_email_template_table

Revision ID: e1f2g3h4i5j6
Revises: m4n5o6p7q8r9
Create Date: 2026-03-14 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e1f2g3h4i5j6"
down_revision: Union[str, None] = "m4n5o6p7q8r9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_template",
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=False, server_default=""),
        sa.Column("text_body", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_type", name="uq_email_template_event_type"),
    )
    op.create_index(
        op.f("ix_email_template_event_type"),
        "email_template",
        ["event_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_email_template_event_type"), table_name="email_template")
    op.drop_table("email_template")

"""S48.3 — admin invoice list: index the sort column.

GET /api/v1/admin/invoices/ always sorts by ``created_at DESC``. ``status`` and
``user_id`` are already indexed (model-level); ``created_at`` is not, so under
load the list forces a full sort — a contributor to the admin invoice list's
tail latency (S48 load profile).

Core migration: resolves standalone (anchors on the prior core head). Pure index
addition, no data change. Guarded + reversible.
"""
from alembic import op

revision = "20260608_inv_admin_idx"
down_revision = "20260608_1000_remove_user_role"
branch_labels = None
depends_on = None

TABLE = "vbwd_user_invoice"
INDEX_NAME = "ix_vbwd_user_invoice_created_at"
COLUMN = "created_at"


def upgrade() -> None:
    op.execute(f'CREATE INDEX IF NOT EXISTS "{INDEX_NAME}" ON "{TABLE}" ("{COLUMN}")')


def downgrade() -> None:
    op.execute(f'DROP INDEX IF EXISTS "{INDEX_NAME}"')

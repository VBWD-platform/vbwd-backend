"""S85.1a — the ``vbwd_price`` table-drop migration is a well-formed CORE
migration that resolves plugin-free.

The persisted ``Price`` model is dead; this CORE migration drops the
``vbwd_price`` table. It anchors on the core chain's own prior head (no
cross-plugin ``down_revision`` / ``depends_on``), so it resolves on a core-only
install. Its ``downgrade`` recreates the bare table (mirroring the original
columns) but does NOT re-add the cross-plugin ``subscription_tarif_plan``
FK — that re-add lives in the subscription migration's own ``downgrade``.
"""
import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # vbwd-backend
MIGRATION = BACKEND_ROOT / "alembic/versions/20260613_1100_drop_vbwd_price.py"

ALEMBIC_VERSION_NUM_MAXLEN = 32


def test_migration_exists_and_chains_off_core_prior_head():
    src = MIGRATION.read_text()
    revision = re.search(r'^revision = "([^"]+)"', src, re.M).group(1)
    down = re.search(r'^down_revision = "([^"]+)"', src, re.M).group(1)
    assert revision == "20260613_1100_drop_price"
    # Anchors on the core chain's prior head (the S84 currency-flags migration).
    assert down == "20260613_1000_curr_flags"
    assert len(revision) <= ALEMBIC_VERSION_NUM_MAXLEN


def test_migration_resolves_plugin_free():
    """A CORE migration must not anchor on or depend on any plugin revision."""
    src = MIGRATION.read_text()
    depends = re.search(r"^depends_on = (.+)$", src, re.M).group(1).strip()
    assert depends == "None", (
        "core vbwd_price-drop must declare depends_on=None so it resolves on a "
        "core-only install (no cross-plugin coupling)."
    )
    # The revision linkage must not anchor on a plugin revision.
    down = re.search(r'^down_revision = "([^"]+)"', src, re.M).group(1)
    assert not down.startswith("20260613_sub")


def test_upgrade_drops_the_table():
    src = MIGRATION.read_text()
    assert 'op.drop_table("vbwd_price")' in src


def test_downgrade_recreates_bare_table_without_cross_plugin_fk():
    src = MIGRATION.read_text()
    downgrade_body = src.split("def downgrade")[1]
    assert "create_table(" in downgrade_body
    assert '"vbwd_price"' in downgrade_body
    # The currency FK belongs to the table itself and is recreated; the
    # subscription FK is NOT (it lives in the subscription migration's down).
    assert "vbwd_currency.id" in downgrade_body
    assert "subscription_tarif_plan" not in downgrade_body

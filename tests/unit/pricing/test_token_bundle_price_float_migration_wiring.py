"""S85.1 — the core token-bundle price-storage migration is wired into the core
chain.

It anchors on the core chain's own prior head (no cross-plugin anchor), widens
the token-bundle money columns to ``Float``, and creates the CORE↔CORE
``token_bundle_tax`` join (both ``vbwd_token_bundle`` and ``vbwd_tax`` are core,
so the agnosticism oracle stays green) with an ``ON DELETE RESTRICT`` FK to the
tax catalog.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]  # vbwd-backend
MIGRATION = REPO_ROOT / "alembic/versions/20260613_1200_token_bundle_price_float.py"

ALEMBIC_VERSION_NUM_MAXLEN = 32


def test_migration_exists_and_chains_off_core_prior_head():
    src = MIGRATION.read_text()
    revision = re.search(r'^revision = "([^"]+)"', src, re.M).group(1)
    down = re.search(r'^down_revision = "([^"]+)"', src, re.M).group(1)
    assert revision == "20260613_1200_tb_price_float"
    # Anchors on the core chain's own current head (the user-groups + vbwd_price
    # merge), keeping core single-headed.
    assert down == "20260613_1200_tags_cf"
    assert len(revision) <= ALEMBIC_VERSION_NUM_MAXLEN


def test_migration_widens_bundle_prices_to_float():
    src = MIGRATION.read_text()
    assert "sa.Float()" in src
    assert "vbwd_token_bundle" in src
    assert "vbwd_token_bundle_purchase" in src


def test_migration_creates_bundle_tax_join_with_restrict_fk():
    src = MIGRATION.read_text()
    assert "token_bundle_tax" in src
    assert "vbwd_token_bundle.id" in src
    assert "vbwd_tax.id" in src
    assert "RESTRICT" in src
    assert "CASCADE" in src


def test_migration_declares_no_cross_plugin_dependency():
    src = MIGRATION.read_text()
    # Core migration must resolve plugin-free.
    assert "depends_on = None" in src

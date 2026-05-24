"""S7/A1 — the subscription plugin owns an Alembic migration branch.

Guards the wiring: the plugin migrations dir is registered, the baseline
revision chains off the prior head, and its id fits the
alembic_version.version_num(32) column (the bug this test pins).
"""
import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
BASELINE = (
    BACKEND_ROOT
    / "plugins/subscription/migrations/versions/20260523_1000_sub_baseline.py"
)

# Alembic's default alembic_version.version_num is VARCHAR(32).
ALEMBIC_VERSION_NUM_MAXLEN = 32


def test_subscription_migrations_dir_registered_in_alembic_ini():
    content = ALEMBIC_INI.read_text()
    assert "plugins/subscription/migrations/versions" in content


def test_baseline_revision_exists_and_chains_off_prior_head():
    src = BASELINE.read_text()
    revision = re.search(r'^revision = "([^"]+)"', src, re.M).group(1)
    down = re.search(r'^down_revision = "([^"]+)"', src, re.M).group(1)
    assert revision == "20260523_1000_sub_baseline"
    assert down == "20260424_1015"


def test_baseline_revision_id_fits_alembic_version_column():
    src = BASELINE.read_text()
    revision = re.search(r'^revision = "([^"]+)"', src, re.M).group(1)
    assert len(revision) <= ALEMBIC_VERSION_NUM_MAXLEN, (
        f"revision id {revision!r} ({len(revision)} chars) exceeds the "
        f"alembic_version.version_num({ALEMBIC_VERSION_NUM_MAXLEN}) column"
    )

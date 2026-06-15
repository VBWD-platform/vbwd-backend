"""S89 Slice 2 — the bulk test-data generator on the exchanger contract.

The generic :meth:`BaseModelExchanger.bulk_seed` manufactures ``count``
deterministic load-test rows through the repository's bulk-insert API (never raw
SQL), keyed ``loadtest-<entity>-<i>``. It is idempotent, supports ``--reset``
(drops only the ``loadtest-``-prefixed rows), and batches inserts so a large
seed is never a single transaction. An exchanger that cannot manufacture rows
raises :class:`UnsupportedOperationError` (Liskov), never silently no-ops.
"""
import pytest

from vbwd.services.data_exchange.base_model_exchanger import (
    LOADTEST_SLUG_PREFIX,
    BaseModelExchanger,
)
from vbwd.services.data_exchange.port import UnsupportedOperationError

from .fakes import (
    FakeExportOnlyExchanger,
    FakeRecord,
    FakeRepository,
    FakeSession,
)


def _make_exchanger(initial_rows=None):
    repo = FakeRepository(initial_rows or [])
    session = FakeSession()
    exchanger = BaseModelExchanger(
        entity_key="widgets",
        label="Widgets",
        cluster="settings",
        natural_key="code",
        model_class=FakeRecord,
        repository=repo,
        session=session,
        public_fields=["code", "label"],
        secret_fields=frozenset({"secret"}),
    )
    return exchanger, repo, session


def test_bulk_seed_creates_count_rows_with_loadtest_keys():
    exchanger, repo, _session = _make_exchanger()
    result = exchanger.bulk_seed(10, batch_size=4)
    assert result.created == 10
    keys = sorted(record.code for record in repo.find_all())
    assert all(key.startswith(LOADTEST_SLUG_PREFIX) for key in keys)
    assert f"{LOADTEST_SLUG_PREFIX}widgets-0" in keys
    assert f"{LOADTEST_SLUG_PREFIX}widgets-9" in keys


def test_bulk_seed_is_idempotent():
    exchanger, repo, _session = _make_exchanger()
    exchanger.bulk_seed(5)
    result = exchanger.bulk_seed(5)
    assert result.created == 0
    assert result.skipped == 5
    assert len(repo.find_all()) == 5


def test_bulk_seed_reset_drops_only_loadtest_rows():
    real_row = FakeRecord("real-product", "Real", "", "x@y")
    exchanger, repo, _session = _make_exchanger([real_row])
    exchanger.bulk_seed(3)
    result = exchanger.bulk_seed(2, reset=True)
    assert result.deleted == 3
    assert result.created == 2
    codes = sorted(record.code for record in repo.find_all())
    # Real row survives; only loadtest-0 / loadtest-1 remain of the seeds.
    assert "real-product" in codes
    assert codes.count("real-product") == 1
    assert sum(code.startswith(LOADTEST_SLUG_PREFIX) for code in codes) == 2


def test_bulk_seed_batches_through_bulk_add():
    """A large seed inserts in batches (not one giant transaction)."""
    exchanger, repo, session = _make_exchanger()
    exchanger.bulk_seed(10, batch_size=3)
    # 10 rows at batch_size 3 → 4 bulk_add batches (3,3,3,1) → 4 commits.
    assert repo.bulk_add_calls == 4
    assert session.commit_count >= 4


def test_export_only_exchanger_rejects_bulk_seed():
    exchanger = FakeExportOnlyExchanger()
    with pytest.raises(UnsupportedOperationError):
        exchanger.bulk_seed(5)

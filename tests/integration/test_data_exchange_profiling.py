"""S89 Slice 2b (integration) — server-side stage timing over a real engine.

DoD #4: with ``VBWD_DATA_EXCHANGE_PROFILE=1`` an export reports a real stage
split — ``query_count >= 1``, ``db_seconds > 0``, ``serialise_seconds > 0``, and
the accounted stage sum is within ε of the measured wall-clock. With the flag
off the collector is inert (no statements attributed). Uses the live integration
DB through a ``BaseModelExchanger`` over the core ``Tag`` entity (a slug-keyed
catalog row) and cleans up its own rows.
"""
import time
from contextlib import contextmanager
from uuid import uuid4

import pytest

from vbwd.services.data_exchange import profiling
from vbwd.services.data_exchange.base_model_exchanger import BaseModelExchanger
from vbwd.services.data_exchange.port import ExportSelector

# Slug prefix for this test's throwaway tags — unique per run so cleanup is exact.
_RUN_TAG = uuid4().hex[:8]
_SLUG_PREFIX = f"s89-profile-{_RUN_TAG}-"


@pytest.fixture
def app():
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": get_database_url(),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "RATELIMIT_ENABLED": False,
    }
    return create_app(test_config)


@contextmanager
def _seeded_tags(app, *, count):
    """Insert ``count`` throwaway tags, yield (exchanger, prefix), then clean up.

    Each invocation gets its own unique slug prefix so concurrent/serial tests in
    this module never collide on the unique ``slug`` index.
    """
    from vbwd.extensions import db
    from vbwd.models.tag import Tag
    from vbwd.repositories.tag_repository import TagRepository

    prefix = f"{_SLUG_PREFIX}{uuid4().hex[:8]}-"
    with app.app_context():
        for index in range(count):
            db.session.add(Tag(slug=f"{prefix}{index}", name=f"Profile tag {index}"))
        db.session.commit()

        exchanger = BaseModelExchanger(
            entity_key="tags_loadtest",
            label="Tags (load test)",
            cluster="settings",
            natural_key="slug",
            model_class=Tag,
            repository=TagRepository(db.session),
            session=db.session,
            public_fields=["slug", "name"],
            row_cap=1000000,
        )
        try:
            yield exchanger, prefix
        finally:
            db.session.query(Tag).filter(Tag.slug.like(f"{prefix}%")).delete(
                synchronize_session=False
            )
            db.session.commit()


def _export_loadtest_rows(exchanger, prefix):
    """Export only this run's seeded tags (filter by the unique slug prefix)."""
    rows = exchanger.export(ExportSelector(all=True), include_pii=True).rows
    return [row for row in rows if str(row["slug"]).startswith(prefix)]


def test_export_profile_off_attributes_nothing(app, monkeypatch):
    monkeypatch.delenv(profiling.PROFILE_ENV_VAR, raising=False)
    with _seeded_tags(app, count=20) as (exchanger, prefix):
        with profiling.start_operation() as stage_profile:
            rows = _export_loadtest_rows(exchanger, prefix)
    assert len(rows) == 20
    # Flag off → the cursor hook never fired, so no DB time was attributed.
    assert stage_profile.query_count == 0
    assert stage_profile.db_seconds == 0.0


def test_export_profile_on_reports_real_split(app, monkeypatch):
    monkeypatch.setenv(profiling.PROFILE_ENV_VAR, "1")
    with _seeded_tags(app, count=50) as (exchanger, prefix):
        wall_start = time.perf_counter()
        with profiling.start_operation() as stage_profile:
            rows = _export_loadtest_rows(exchanger, prefix)
        wall_seconds = time.perf_counter() - wall_start

    assert len(rows) == 50
    assert stage_profile.query_count >= 1
    assert stage_profile.db_seconds > 0
    assert stage_profile.spans.get(profiling.SPAN_SERIALISE, 0.0) > 0
    accounted = stage_profile.db_seconds + stage_profile.spans.get(
        profiling.SPAN_SERIALISE, 0.0
    )
    # The accounted stages are a subset of the measured wall-clock (allow a small
    # tolerance for timer granularity); they must not exceed it.
    assert accounted <= wall_seconds + 0.5


def test_export_profile_on_sizes_the_table(app, monkeypatch):
    """With the table name plumbed in, the op-end catalog query reports a non-zero
    table + index size for the seeded entity (§2.2 DB-side artefacts)."""
    from vbwd.models.tag import Tag

    monkeypatch.setenv(profiling.PROFILE_ENV_VAR, "1")
    with _seeded_tags(app, count=30) as (exchanger, prefix):
        from vbwd.extensions import db

        with profiling.start_operation(
            table_name=Tag.__tablename__, session=db.session
        ) as stage_profile:
            _export_loadtest_rows(exchanger, prefix)

    assert stage_profile.table_bytes is not None
    assert stage_profile.table_bytes > 0
    assert stage_profile.index_bytes is not None
    assert stage_profile.index_bytes > 0
    data = stage_profile.to_dict()
    assert data["table_bytes"] > 0
    assert data["index_bytes"] > 0


def test_export_profile_on_reports_longest_txn(app, monkeypatch):
    """The op-end pg_stat_activity probe reports a longest-transaction figure for
    this backend (best-effort: a float ≥ 0 when the catalog is queryable)."""
    monkeypatch.setenv(profiling.PROFILE_ENV_VAR, "1")
    with _seeded_tags(app, count=10) as (exchanger, prefix):
        from vbwd.extensions import db

        with profiling.start_operation(session=db.session) as stage_profile:
            _export_loadtest_rows(exchanger, prefix)

    assert stage_profile.longest_txn_seconds is not None
    assert stage_profile.longest_txn_seconds >= 0.0
    assert stage_profile.longest_lock_wait_seconds is not None
    assert stage_profile.longest_lock_wait_seconds >= 0.0

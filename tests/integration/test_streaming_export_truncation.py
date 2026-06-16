"""S89 reproduction — HTTP streaming NDJSON export must not silently truncate.

The CLI export of a large table returns every row, but the HTTP streaming
NDJSON path (``POST /api/v1/admin/data-exchange/<key>/export`` with
``{"format": "ndjson"}``) was observed to truncate after a variable number of
rows (bookings 0 rows, plans a few, products some) while a smaller table came
back whole. The streaming generator runs lazily under
``stream_with_context`` *after* the view returns, so the ``yield_per`` server-
side cursor's connection lifecycle must outlive the whole stream.

This test seeds a real table well beyond one server-side cursor batch, then
asserts the streamed body carries the header line plus EVERY seeded row.
"""
from uuid import uuid4

import pytest

from vbwd.services.data_exchange.base_model_exchanger import BaseModelExchanger
from vbwd.services.data_exchange.registry import data_exchange_registry

# Seed comfortably past the 5000-row yield_per batch so the server-side cursor
# must survive across the streamed teardown boundary.
_SEED_COUNT = 6000
_RUN_TAG = uuid4().hex[:8]
_SLUG_PREFIX = f"s89-stream-{_RUN_TAG}-"
_ENTITY_KEY = f"tags_stream_{_RUN_TAG}"


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


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded_tag_exchanger(app):
    """Seed ``_SEED_COUNT`` tags, register a real exchanger, yield, then clean up."""
    from vbwd.extensions import db
    from vbwd.models.tag import Tag
    from vbwd.repositories.tag_repository import TagRepository

    with app.app_context():
        db.session.bulk_save_objects(
            [
                Tag(slug=f"{_SLUG_PREFIX}{index}", name=f"Stream tag {index}")
                for index in range(_SEED_COUNT)
            ]
        )
        db.session.commit()

        exchanger = BaseModelExchanger(
            entity_key=_ENTITY_KEY,
            label="Tags (stream test)",
            cluster="settings",
            natural_key="slug",
            model_class=Tag,
            repository=TagRepository(db.session),
            session=db.session,
            public_fields=["slug", "name"],
            row_cap=10_000_000,
        )
        data_exchange_registry.register(exchanger)
        try:
            yield exchanger
        finally:
            data_exchange_registry.clear()
            db.session.query(Tag).filter(Tag.slug.like(f"{_SLUG_PREFIX}%")).delete(
                synchronize_session=False
            )
            db.session.commit()


def _admin_headers(app):
    """Mint a real admin JWT against the live test user so the route authorises.

    The seeded test entity is in the ``settings`` cluster, so an admin with the
    ``settings.view`` permission can export it (no superadmin required).
    """
    from vbwd.extensions import db
    from vbwd.repositories.user_repository import UserRepository
    from vbwd.services.auth_service import AuthService

    with app.app_context():
        user = UserRepository(db.session).find_by_email("admin@example.com")
        if user is None:
            pytest.skip("admin@example.com not seeded in the integration DB")
        if not user.is_admin:
            pytest.skip("admin@example.com is not an admin in the integration DB")
        if not user.has_permission("settings.view"):
            pytest.skip("admin@example.com lacks settings.view permission")
        auth_service = AuthService(user_repository=UserRepository(db.session))
        token = auth_service.generate_access_token(user.id, user.email)
    return {"Authorization": f"Bearer {token}"}


def test_export_stream_survives_session_remove_mid_iteration(seeded_tag_exchanger, app):
    """Root-cause regression: the lazy export iterator must outlive a session reset.

    The HTTP stream runs lazily under ``stream_with_context`` *after* the view
    returns, so the app-context teardown's ``db.session.remove()`` can fire
    between chunks. A server-side ``yield_per`` cursor dies at that point
    (``named cursor isn't valid anymore``) and the stream truncates silently at
    a chunk boundary. Keyset pagination must instead yield every row even when
    the session is removed mid-iteration. This reproduces the teardown race
    deterministically (the buffered test client cannot).
    """
    from vbwd.extensions import db
    from vbwd.services.data_exchange.port import ExportSelector

    with app.app_context():
        chunks = seeded_tag_exchanger.iter_export(
            ExportSelector(all=True), chunk_size=2000, include_pii=True
        )
        seeded = 0
        first_chunk = next(chunks)
        seeded += sum(
            1 for row in first_chunk if str(row["slug"]).startswith(_SLUG_PREFIX)
        )
        # Simulate the post-view app-context teardown firing mid-stream.
        db.session.remove()
        for chunk in chunks:
            seeded += sum(
                1 for row in chunk if str(row["slug"]).startswith(_SLUG_PREFIX)
            )
    assert seeded == _SEED_COUNT, (
        f"export iterator truncated after session.remove(): got {seeded} seeded "
        f"rows, expected {_SEED_COUNT}"
    )


def test_streamed_ndjson_export_returns_every_seeded_row(
    seeded_tag_exchanger, app, client
):
    headers = _admin_headers(app)
    response = client.post(
        f"/api/v1/admin/data-exchange/{_ENTITY_KEY}/export",
        json={"all": True, "format": "ndjson"},
        headers=headers,
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.mimetype == "application/x-ndjson"

    body = response.get_data(as_text=True)
    lines = [line for line in body.splitlines() if line.strip()]
    # Count only THIS run's seeded rows (the live DB may hold other tags).
    seeded_lines = [line for line in lines if _SLUG_PREFIX in line]
    assert len(seeded_lines) == _SEED_COUNT, (
        f"streamed body truncated: got {len(seeded_lines)} seeded rows, "
        f"expected {_SEED_COUNT}"
    )

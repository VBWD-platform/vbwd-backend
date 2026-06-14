"""S77 slice 2 — admin routes for tag catalog, custom-field defs, entity-type
listing, and the generic per-entity value endpoints (live-DB integration).

Mirrors ``test_admin_invoices_query_count``: ``create_app`` against the live
integration DB, the Flask ``test_client``, and a monkeypatched auth that grants
a configurable permission set so the per-entity ``manage_permission`` gating can
be exercised (allow / 403 / 404-unregistered). Each test cleans up its rows.
"""
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import event

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User


@pytest.fixture
def app():
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    return create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": get_database_url(),
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "RATELIMIT_ENABLED": False,
        }
    )


@contextmanager
def _admin(app):
    """Create an admin user, yield it, then delete it (DB left clean)."""
    from vbwd.extensions import db

    with app.app_context():
        admin = User(
            id=uuid4(),
            email=f"s77-admin-{uuid4().hex[:8]}@example.com",
            password_hash="x",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id
        try:
            yield admin
        finally:
            obj = db.session.get(User, admin_id)
            if obj:
                db.session.delete(obj)
            db.session.commit()


def _auth_as(monkeypatch, admin, granted_permissions):
    """Authenticate the test client as ``admin`` with a fixed permission set."""
    from unittest.mock import MagicMock

    import vbwd.middleware.auth as auth_mod

    repo = MagicMock()
    repo.find_by_id.return_value = admin
    svc = MagicMock()
    svc.verify_token.return_value = str(admin.id)
    monkeypatch.setattr(auth_mod, "UserRepository", lambda *a, **k: repo)
    monkeypatch.setattr(auth_mod, "AuthService", lambda *a, **k: svc)
    monkeypatch.setattr(type(admin), "is_admin", property(lambda self: True))
    granted = set(granted_permissions)
    monkeypatch.setattr(
        type(admin),
        "has_permission",
        lambda self, perm: perm in granted,
    )


HEADERS = {"Authorization": "Bearer valid"}


@contextmanager
def _cleanup_tags(app, *slugs):
    from vbwd.extensions import db
    from vbwd.models.tag import Tag

    try:
        yield
    finally:
        with app.app_context():
            db.session.query(Tag).filter(Tag.slug.in_(slugs)).delete(
                synchronize_session=False
            )
            db.session.commit()


@contextmanager
def _cleanup_defs(app, entity_type, *keys):
    from vbwd.extensions import db
    from vbwd.models.custom_field_def import CustomFieldDef
    from vbwd.models.custom_field_value import CustomFieldValue

    try:
        yield
    finally:
        with app.app_context():
            db.session.query(CustomFieldValue).filter(
                CustomFieldValue.entity_type == entity_type,
                CustomFieldValue.field_key.in_(keys),
            ).delete(synchronize_session=False)
            db.session.query(CustomFieldDef).filter(
                CustomFieldDef.entity_type == entity_type,
                CustomFieldDef.key.in_(keys),
            ).delete(synchronize_session=False)
            db.session.commit()


# ── tag catalog CRUD + bulk-delete + stats column ───────────────────────────


def test_tag_crud_and_stats_in_list(app, monkeypatch):
    slug = f"s77-tag-{uuid4().hex[:8]}"
    with _admin(app) as admin, _cleanup_tags(app, slug):
        # settings.manage gates the catalog; users.manage gates the user value
        # endpoint used below to attach the tag so its usage stat becomes 2.
        _auth_as(monkeypatch, admin, {"settings.manage", "users.manage"})
        client = app.test_client()

        created = client.post(
            "/api/v1/admin/tags",
            json={"slug": slug, "name": "Tag", "parent_entity_type": "user"},
            headers=HEADERS,
        )
        assert created.status_code == 201, created.get_json()
        assert created.get_json()["tag"]["slug"] == slug

        # attach the tag to two users so its usage stat is 2
        client.put(
            f"/api/v1/admin/user/{uuid4()}/tags",
            json={"tags": [slug]},
            headers=HEADERS,
        )
        client.put(
            f"/api/v1/admin/user/{uuid4()}/tags",
            json={"tags": [slug]},
            headers=HEADERS,
        )

        listed = client.get(
            "/api/v1/admin/tags?parent_entity_type=user", headers=HEADERS
        )
        assert listed.status_code == 200, listed.get_json()
        row = next(t for t in listed.get_json()["tags"] if t["slug"] == slug)
        assert row["stats"] == 2

        updated = client.put(
            f"/api/v1/admin/tags/{slug}",
            json={"name": "Renamed"},
            headers=HEADERS,
        )
        assert updated.status_code == 200
        assert updated.get_json()["tag"]["name"] == "Renamed"

        deleted = client.delete(f"/api/v1/admin/tags/{slug}", headers=HEADERS)
        assert deleted.status_code == 200


def test_tag_list_stats_is_one_grouped_query(app, monkeypatch):
    slug_a = f"s77-a-{uuid4().hex[:8]}"
    slug_b = f"s77-b-{uuid4().hex[:8]}"
    with _admin(app) as admin, _cleanup_tags(app, slug_a, slug_b):
        _auth_as(monkeypatch, admin, {"settings.manage", "users.manage"})
        client = app.test_client()
        for slug in (slug_a, slug_b):
            client.post(
                "/api/v1/admin/tags",
                json={"slug": slug, "name": slug, "parent_entity_type": "user"},
                headers=HEADERS,
            )
        client.put(
            f"/api/v1/admin/user/{uuid4()}/tags",
            json={"tags": [slug_a, slug_b]},
            headers=HEADERS,
        )

        from vbwd.extensions import db

        with app.app_context():
            engine = db.session.get_bind()
        count_statements = []

        def _record(conn, cursor, statement, params, context, executemany):
            stripped = statement.lstrip().upper()
            if stripped.startswith("SELECT") and " COUNT(" in stripped:
                count_statements.append(statement)

        event.listen(engine, "before_cursor_execute", _record)
        try:
            listed = client.get(
                "/api/v1/admin/tags?parent_entity_type=user", headers=HEADERS
            )
        finally:
            event.remove(engine, "before_cursor_execute", _record)
        assert listed.status_code == 200
        # exactly one grouped COUNT over entity_tag for the whole page (no N+1)
        assert len(count_statements) == 1, count_statements


def test_tag_bulk_delete(app, monkeypatch):
    slug_a = f"s77-bd-{uuid4().hex[:8]}"
    slug_b = f"s77-bd-{uuid4().hex[:8]}"
    with _admin(app) as admin, _cleanup_tags(app, slug_a, slug_b):
        _auth_as(monkeypatch, admin, {"settings.manage"})
        client = app.test_client()
        for slug in (slug_a, slug_b):
            client.post(
                "/api/v1/admin/tags",
                json={"slug": slug, "name": slug},
                headers=HEADERS,
            )
        resp = client.post(
            "/api/v1/admin/tags/bulk-delete",
            json={"slugs": [slug_a, slug_b]},
            headers=HEADERS,
        )
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["deleted"] == 2
        remaining = client.get("/api/v1/admin/tags", headers=HEADERS).get_json()["tags"]
        slugs = {t["slug"] for t in remaining}
        assert slug_a not in slugs and slug_b not in slugs


def test_tag_routes_require_settings_manage(app, monkeypatch):
    with _admin(app) as admin:
        _auth_as(monkeypatch, admin, {"settings.view"})  # not manage
        client = app.test_client()
        resp = client.get("/api/v1/admin/tags", headers=HEADERS)
        assert resp.status_code == 403


# ── custom-field-def CRUD + filters ─────────────────────────────────────────


def test_custom_field_def_crud_and_filters(app, monkeypatch):
    key = f"s77-cf-{uuid4().hex[:8]}"
    with _admin(app) as admin, _cleanup_defs(app, "user", key):
        _auth_as(monkeypatch, admin, {"settings.manage"})
        client = app.test_client()

        created = client.post(
            "/api/v1/admin/custom-fields",
            json={
                "entity_type": "user",
                "key": key,
                "label": "Score",
                "type": "number",
            },
            headers=HEADERS,
        )
        assert created.status_code == 201, created.get_json()
        def_id = created.get_json()["custom_field"]["id"]

        by_entity = client.get(
            "/api/v1/admin/custom-fields?entity_type=user", headers=HEADERS
        )
        assert by_entity.status_code == 200
        assert any(d["key"] == key for d in by_entity.get_json()["custom_fields"])

        by_type_text = client.get(
            "/api/v1/admin/custom-fields?type=text", headers=HEADERS
        )
        assert all(
            d["type"] == "text" for d in by_type_text.get_json()["custom_fields"]
        )

        updated = client.put(
            f"/api/v1/admin/custom-fields/{def_id}",
            json={"label": "Renamed", "is_active": False},
            headers=HEADERS,
        )
        assert updated.status_code == 200
        assert updated.get_json()["custom_field"]["label"] == "Renamed"
        assert updated.get_json()["custom_field"]["is_active"] is False

        deleted = client.delete(
            f"/api/v1/admin/custom-fields/{def_id}", headers=HEADERS
        )
        assert deleted.status_code == 200


def test_custom_field_def_create_bad_type_is_400(app, monkeypatch):
    with _admin(app) as admin:
        _auth_as(monkeypatch, admin, {"settings.manage"})
        client = app.test_client()
        resp = client.post(
            "/api/v1/admin/custom-fields",
            json={
                "entity_type": "user",
                "key": "bad",
                "label": "Bad",
                "type": "nonsense",
            },
            headers=HEADERS,
        )
        assert resp.status_code == 400


def test_custom_field_def_bulk_delete(app, monkeypatch):
    key_a = f"s77-bd-{uuid4().hex[:8]}"
    key_b = f"s77-bd-{uuid4().hex[:8]}"
    with _admin(app) as admin, _cleanup_defs(app, "user", key_a, key_b):
        _auth_as(monkeypatch, admin, {"settings.manage"})
        client = app.test_client()
        ids = []
        for key in (key_a, key_b):
            created = client.post(
                "/api/v1/admin/custom-fields",
                json={"entity_type": "user", "key": key, "label": key, "type": "text"},
                headers=HEADERS,
            )
            ids.append(created.get_json()["custom_field"]["id"])
        resp = client.post(
            "/api/v1/admin/custom-fields/bulk-delete",
            json={"ids": ids},
            headers=HEADERS,
        )
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["deleted"] == 2


# ── entity-type listing ──────────────────────────────────────────────────────


def test_entity_type_listing(app, monkeypatch):
    with _admin(app) as admin:
        _auth_as(monkeypatch, admin, {"settings.manage"})
        client = app.test_client()
        resp = client.get("/api/v1/admin/custom-field-entity-types", headers=HEADERS)
        assert resp.status_code == 200, resp.get_json()
        types = resp.get_json()["entity_types"]
        user = next(t for t in types if t["entity_type"] == "user")
        assert user["label"] == "User"
        assert user["manage_permission"] == "users.manage"


# ── generic value endpoints (gated by the entity's manage_permission) ────────


def test_value_endpoints_tags_full_replace(app, monkeypatch):
    slug = f"s77-v-{uuid4().hex[:8]}"
    entity_id = uuid4()
    # the "user" entity type is gated by users.manage (its registration)
    with _admin(app) as admin, _cleanup_tags(app, slug):
        _auth_as(monkeypatch, admin, {"users.manage"})
        client = app.test_client()
        put = client.put(
            f"/api/v1/admin/user/{entity_id}/tags",
            json={"tags": [slug]},
            headers=HEADERS,
        )
        assert put.status_code == 200, put.get_json()
        got = client.get(f"/api/v1/admin/user/{entity_id}/tags", headers=HEADERS)
        assert got.status_code == 200
        assert got.get_json()["tags"] == [slug]
        # full replace with empty detaches
        client.put(
            f"/api/v1/admin/user/{entity_id}/tags",
            json={"tags": []},
            headers=HEADERS,
        )
        cleared = client.get(f"/api/v1/admin/user/{entity_id}/tags", headers=HEADERS)
        assert cleared.get_json()["tags"] == []


def test_value_endpoints_custom_fields_partial_upsert_and_none_clears(app, monkeypatch):
    key_one = f"s77-k1-{uuid4().hex[:8]}"
    key_two = f"s77-k2-{uuid4().hex[:8]}"
    entity_id = uuid4()
    with _admin(app) as admin, _cleanup_defs(app, "user", key_one, key_two):
        _auth_as(monkeypatch, admin, {"settings.manage", "users.manage"})
        client = app.test_client()
        for key in (key_one, key_two):
            client.post(
                "/api/v1/admin/custom-fields",
                json={"entity_type": "user", "key": key, "label": key, "type": "text"},
                headers=HEADERS,
            )
        client.put(
            f"/api/v1/admin/user/{entity_id}/custom-fields",
            json={"custom_fields": {key_one: "one", key_two: "two"}},
            headers=HEADERS,
        )
        # partial upsert: only key_one submitted
        client.put(
            f"/api/v1/admin/user/{entity_id}/custom-fields",
            json={"custom_fields": {key_one: "ONE"}},
            headers=HEADERS,
        )
        got = client.get(
            f"/api/v1/admin/user/{entity_id}/custom-fields", headers=HEADERS
        )
        assert got.get_json()["custom_fields"] == {key_one: "ONE", key_two: "two"}
        # None clears just that key
        client.put(
            f"/api/v1/admin/user/{entity_id}/custom-fields",
            json={"custom_fields": {key_one: None}},
            headers=HEADERS,
        )
        got = client.get(
            f"/api/v1/admin/user/{entity_id}/custom-fields", headers=HEADERS
        )
        assert got.get_json()["custom_fields"] == {key_two: "two"}


def test_value_endpoints_unregistered_entity_type_is_404(app, monkeypatch):
    with _admin(app) as admin:
        _auth_as(monkeypatch, admin, {"users.manage", "settings.manage"})
        client = app.test_client()
        resp = client.get(
            f"/api/v1/admin/never_registered/{uuid4()}/tags", headers=HEADERS
        )
        assert resp.status_code == 404


def test_value_endpoints_missing_manage_permission_is_403(app, monkeypatch):
    # "user" requires users.manage; grant only settings.manage
    with _admin(app) as admin:
        _auth_as(monkeypatch, admin, {"settings.manage"})
        client = app.test_client()
        resp = client.get(f"/api/v1/admin/user/{uuid4()}/tags", headers=HEADERS)
        assert resp.status_code == 403


def test_value_endpoints_bad_custom_field_value_is_400(app, monkeypatch):
    key = f"s77-bad-{uuid4().hex[:8]}"
    entity_id = uuid4()
    with _admin(app) as admin, _cleanup_defs(app, "user", key):
        _auth_as(monkeypatch, admin, {"settings.manage", "users.manage"})
        client = app.test_client()
        client.post(
            "/api/v1/admin/custom-fields",
            json={"entity_type": "user", "key": key, "label": key, "type": "number"},
            headers=HEADERS,
        )
        resp = client.put(
            f"/api/v1/admin/user/{entity_id}/custom-fields",
            json={"custom_fields": {key: "not-a-number"}},
            headers=HEADERS,
        )
        assert resp.status_code == 400


def test_value_endpoints_unknown_field_key_is_400(app, monkeypatch):
    with _admin(app) as admin:
        _auth_as(monkeypatch, admin, {"users.manage"})
        client = app.test_client()
        resp = client.put(
            f"/api/v1/admin/user/{uuid4()}/custom-fields",
            json={"custom_fields": {"never_defined": "x"}},
            headers=HEADERS,
        )
        assert resp.status_code == 400

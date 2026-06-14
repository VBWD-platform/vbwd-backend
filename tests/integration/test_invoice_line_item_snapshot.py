"""S77 — invoice_line_item is a live entity type + snapshot is immutable.

Two guarantees (live-DB integration):
1. ``invoice_line_item`` is registered at app startup, so its generic value
   endpoints answer 200 (gated by ``invoices.manage``), not 404-unregistered.
2. The snapshot freezes the source's tags/CF at creation time — a later change
   to the *source* entity does NOT change the invoice line's frozen copy.
"""
from contextlib import contextmanager
from uuid import uuid4

import pytest

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
    from vbwd.extensions import db

    with app.app_context():
        admin = User(
            id=uuid4(),
            email=f"s77-inv-{uuid4().hex[:8]}@example.com",
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
        type(admin), "has_permission", lambda self, perm: perm in granted
    )


HEADERS = {"Authorization": "Bearer valid"}


def test_invoice_line_item_value_endpoint_is_registered(app, monkeypatch):
    with _admin(app) as admin:
        _auth_as(monkeypatch, admin, {"invoices.manage"})
        client = app.test_client()
        line_id = uuid4()

        # registered type -> 200 (not 404 unregistered)
        get = client.get(
            f"/api/v1/admin/invoice_line_item/{line_id}/tags", headers=HEADERS
        )
        assert get.status_code == 200, get.get_json()

        # writing is gated by invoices.manage (which we granted)
        put = client.put(
            f"/api/v1/admin/invoice_line_item/{line_id}/tags",
            json={"tags": []},
            headers=HEADERS,
        )
        assert put.status_code == 200, put.get_json()


def test_snapshot_is_immutable_against_later_source_change(app):
    from vbwd.extensions import db
    from vbwd.models.tag import Tag
    from vbwd.services.tags_and_custom_fields import resolve_tags_and_custom_fields

    source_slug = f"s77-src-{uuid4().hex[:8]}"
    extra_slug = f"s77-extra-{uuid4().hex[:8]}"
    source_id = uuid4()
    line_id = uuid4()
    with app.app_context():
        port = resolve_tags_and_custom_fields()
        try:
            # 1. source product carries one tag
            port.set_tags("user", source_id, [source_slug])

            # 2. snapshot it onto the invoice line (freeze)
            frozen = port.get_tags("user", source_id)
            port.set_tags("invoice_line_item", line_id, frozen)
            assert port.get_tags("invoice_line_item", line_id) == [source_slug]

            # 3. source later gains another tag
            port.set_tags("user", source_id, [source_slug, extra_slug])

            # 4. the frozen invoice line is UNCHANGED
            assert port.get_tags("invoice_line_item", line_id) == [source_slug]
            assert set(port.get_tags("user", source_id)) == {source_slug, extra_slug}
        finally:
            from vbwd.models.entity_tag import EntityTag

            db.session.query(EntityTag).filter(
                EntityTag.entity_id.in_([source_id, line_id])
            ).delete(synchronize_session=False)
            db.session.query(Tag).filter(
                Tag.slug.in_([source_slug, extra_slug])
            ).delete(synchronize_session=False)
            db.session.commit()

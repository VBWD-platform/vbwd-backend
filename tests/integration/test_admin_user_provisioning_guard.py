"""Route contract for the user-provisioning guard veto (live-DB integration).

``POST /api/v1/admin/users`` runs the registered provisioning guards; when a
guard vetoes, the route echoes the structured veto so the frontend can render a
call-to-action hyperlink:

    {"error": <message>, "code": <code>, "action": {"label": ..., "url": ...}}

``action`` is omitted when the guard sets no label/url. With no guard
registered the route creates the user exactly as before (no behaviour change).

Mirrors ``test_admin_tags_custom_fields_routes``: ``create_app`` against the
live integration DB, the Flask ``test_client``, and a monkeypatched auth that
grants ``users.manage`` so the create route is reachable.
"""
from contextlib import contextmanager
from uuid import uuid4

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User
from vbwd.registries.user_provisioning_guard_registry import (
    UserProvisioningBlocked,
    clear_user_provisioning_guards,
    register_user_provisioning_guard,
)


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


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_user_provisioning_guards()
    yield
    clear_user_provisioning_guards()


@contextmanager
def _admin(app):
    from vbwd.extensions import db

    with app.app_context():
        admin = User(
            id=uuid4(),
            email=f"prov-admin-{uuid4().hex[:8]}@example.com",
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


def _auth_as(monkeypatch, admin):
    from unittest.mock import MagicMock

    import vbwd.middleware.auth as auth_mod

    repo = MagicMock()
    repo.find_by_id.return_value = admin
    svc = MagicMock()
    svc.verify_token.return_value = str(admin.id)
    monkeypatch.setattr(auth_mod, "UserRepository", lambda *a, **k: repo)
    monkeypatch.setattr(auth_mod, "AuthService", lambda *a, **k: svc)
    monkeypatch.setattr(type(admin), "is_admin", property(lambda self: True))
    monkeypatch.setattr(
        type(admin), "has_permission", lambda self, perm: perm == "users.manage"
    )


HEADERS = {"Authorization": "Bearer valid"}


def _new_user_payload():
    return {
        "email": f"provisioned-{uuid4().hex[:8]}@example.com",
        "password": "password123",
        "role": "USER",
    }


def test_guard_veto_returns_status_and_structured_body(app, monkeypatch):
    def blocking_guard(request):
        assert request.acting_user_id is not None  # g.user_id reached the guard
        raise UserProvisioningBlocked(
            "no", code="X", status=402, action_label="Buy", action_url="/buy"
        )

    register_user_provisioning_guard(blocking_guard)

    with _admin(app) as admin:
        _auth_as(monkeypatch, admin)
        client = app.test_client()
        response = client.post(
            "/api/v1/admin/users/", json=_new_user_payload(), headers=HEADERS
        )

    assert response.status_code == 402
    body = response.get_json()
    assert body == {
        "error": "no",
        "code": "X",
        "action": {"label": "Buy", "url": "/buy"},
    }


def test_guard_veto_omits_action_when_unset(app, monkeypatch):
    def blocking_guard(_request):
        raise UserProvisioningBlocked("denied", code="SEAT_LIMIT_REACHED")

    register_user_provisioning_guard(blocking_guard)

    with _admin(app) as admin:
        _auth_as(monkeypatch, admin)
        client = app.test_client()
        response = client.post(
            "/api/v1/admin/users/", json=_new_user_payload(), headers=HEADERS
        )

    assert response.status_code == 403
    body = response.get_json()
    assert body == {"error": "denied", "code": "SEAT_LIMIT_REACHED"}
    assert "action" not in body


def test_no_guard_creates_user_unchanged(app, monkeypatch):
    from vbwd.extensions import db

    payload = _new_user_payload()
    created_id = None
    with _admin(app) as admin:
        _auth_as(monkeypatch, admin)
        client = app.test_client()
        response = client.post("/api/v1/admin/users/", json=payload, headers=HEADERS)
        assert response.status_code == 201, response.get_data(as_text=True)
        created_id = response.get_json()["id"]
        # Clean up the created user inside the same app context.
        with app.app_context():
            obj = db.session.get(User, created_id)
            if obj:
                db.session.delete(obj)
                db.session.commit()

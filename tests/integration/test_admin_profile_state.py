"""State/Region persists through the admin-profile endpoint.

Proves ``PUT /api/v1/admin/profile`` carrying ``state`` stores it and a
subsequent ``GET /api/v1/admin/profile`` returns it. Mirrors
``test_user_details_state``: ``create_app`` against the live integration DB,
the Flask ``test_client``, and a monkeypatched auth that resolves the request
to a real admin user row.
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
def _admin_user(app):
    from vbwd.extensions import db

    with app.app_context():
        user = User(
            id=uuid4(),
            email=f"admin-state-{uuid4().hex[:8]}@example.com",
            password_hash="x",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        try:
            yield user
        finally:
            details = user.details
            if details:
                db.session.delete(details)
            obj = db.session.get(User, user_id)
            if obj:
                db.session.delete(obj)
            db.session.commit()


def _auth_as(monkeypatch, user):
    from unittest.mock import MagicMock

    import vbwd.middleware.auth as auth_mod

    repo = MagicMock()
    repo.find_by_id.return_value = user
    svc = MagicMock()
    svc.verify_token.return_value = str(user.id)
    monkeypatch.setattr(auth_mod, "UserRepository", lambda *a, **k: repo)
    monkeypatch.setattr(auth_mod, "AuthService", lambda *a, **k: svc)


HEADERS = {"Authorization": "Bearer valid"}


def test_admin_profile_persists_state(app, monkeypatch):
    with _admin_user(app) as user:
        _auth_as(monkeypatch, user)
        client = app.test_client()

        put_response = client.put(
            "/api/v1/admin/profile",
            json={
                "first_name": "Ada",
                "city": "Munich",
                "state": "Bavaria",
                "postal_code": "80331",
                "country": "DE",
            },
            headers=HEADERS,
        )
        assert put_response.status_code == 200, put_response.get_data(as_text=True)
        put_body = put_response.get_json()
        assert put_body["user"]["details"]["state"] == "Bavaria"

        get_response = client.get("/api/v1/admin/profile", headers=HEADERS)
        assert get_response.status_code == 200
        get_body = get_response.get_json()
        assert get_body["user"]["details"]["state"] == "Bavaria"

"""State/Region persists on the user address against the real schema.

Proves the round-trip the frontend relies on: an authenticated
``PUT /api/v1/user/details`` that carries ``state`` (and ``postal_code``)
stores both, and a subsequent ``GET /api/v1/user/details`` returns them.

Follows ``test_admin_user_provisioning_guard``: ``create_app`` against the
live integration DB, the Flask ``test_client``, and a monkeypatched auth that
resolves the request to a real user row so ``update_user_details`` writes
through the container-built service to the actual database.
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
def _user(app):
    from vbwd.extensions import db

    with app.app_context():
        user = User(
            id=uuid4(),
            email=f"state-user-{uuid4().hex[:8]}@example.com",
            password_hash="x",
            status=UserStatus.ACTIVE,
            role=UserRole.USER,
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


def test_state_and_postal_code_round_trip(app, monkeypatch):
    with _user(app) as user:
        _auth_as(monkeypatch, user)
        client = app.test_client()

        put_response = client.put(
            "/api/v1/user/details",
            json={
                "first_name": "Ada",
                "last_name": "Lovelace",
                "address_line_1": "1 Analytical Way",
                "city": "LA",
                "state": "California",
                "postal_code": "90001",
                "country": "US",
            },
            headers=HEADERS,
        )
        assert put_response.status_code == 200, put_response.get_data(as_text=True)
        put_body = put_response.get_json()
        assert put_body["state"] == "California"
        assert put_body["postal_code"] == "90001"

        get_response = client.get("/api/v1/user/details", headers=HEADERS)
        assert get_response.status_code == 200
        get_body = get_response.get_json()
        assert get_body["state"] == "California"
        assert get_body["postal_code"] == "90001"

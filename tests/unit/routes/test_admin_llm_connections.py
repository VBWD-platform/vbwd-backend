"""Unit tests for the admin LLM-connection routes (S97.2).

DB-backed (like ``test_admin_currency``): hits the live session through the
``client`` fixture with mocked auth. An autouse fixture ensures the
``vbwd_llm_connection`` table exists and starts each test from an empty table so
the single-default invariant assertions are deterministic.

Asserts: reads/writes are permission-gated (401/403); the list never returns a
full key (only the 16-preview); make-default is single + idempotent; bulk
activate/deactivate; resolving by slug returns the selected connection, not the
default.
"""
from unittest.mock import patch
from uuid import uuid4

import pytest

from tests.fixtures.access import (
    make_user_no_permissions,
    make_user_with_permissions,
)

LIVE_KEY = "sk-live-0123456789abcdefGHIJKLMNOP-secret-tail"
KEY_PREVIEW = "sk-live-01234567"  # exactly 16 chars
BASE = "/api/v1/admin/llm-connections"


def _auth_headers():
    return {"Authorization": "Bearer valid"}


def _mock_auth(mock_repo_cls, mock_auth_cls, user):
    mock_repo_cls.return_value.find_by_id.return_value = user
    mock_auth_cls.return_value.verify_token.return_value = str(uuid4())


@pytest.fixture(autouse=True)
def clean_table(app):
    from vbwd.extensions import db
    from vbwd.models.llm_connection import LlmConnection

    with app.app_context():
        LlmConnection.__table__.create(bind=db.engine, checkfirst=True)
        db.session.query(LlmConnection).delete()
        db.session.commit()
    yield
    with app.app_context():
        db.session.query(LlmConnection).delete()
        db.session.commit()


def _seed(app, slug, *, active=True, default=False, model="claude-3-5-sonnet-latest"):
    from vbwd.extensions import db
    from vbwd.models.llm_connection import LlmConnection

    with app.app_context():
        connection = LlmConnection(
            id=uuid4(),
            slug=slug,
            connection_name=f"Conn {slug}",
            api_endpoint="https://api.anthropic.com",
            api_key=LIVE_KEY,
            model=model,
            is_active=active,
            is_default=default,
        )
        db.session.add(connection)
        db.session.commit()
        return str(connection.id)


class TestPermissions:
    def test_list_unauthenticated(self, client):
        assert client.get(BASE).status_code == 401

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_forbidden_without_view(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(mock_repo_cls, mock_auth_cls, make_user_no_permissions())
        assert client.get(BASE, headers=_auth_headers()).status_code == 403

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_forbidden_with_only_view(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _mock_auth(
            mock_repo_cls,
            mock_auth_cls,
            make_user_with_permissions("llm.connections.view"),
        )
        response = client.post(
            BASE,
            headers=_auth_headers(),
            json={
                "slug": "x",
                "connection_name": "X",
                "model": "gpt-4o-mini",
                "api_key": LIVE_KEY,
            },
        )
        assert response.status_code == 403


class TestListMasking:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_returns_masked_key_only(
        self, mock_repo_cls, mock_auth_cls, client, app
    ):
        _seed(app, "claude-default")
        _mock_auth(
            mock_repo_cls,
            mock_auth_cls,
            make_user_with_permissions("llm.connections.view"),
        )
        response = client.get(BASE, headers=_auth_headers())
        assert response.status_code == 200
        rows = response.get_json()["connections"]
        assert len(rows) == 1
        key_value = rows[0]["api_key"]
        assert LIVE_KEY not in key_value
        assert key_value.startswith(KEY_PREVIEW)
        assert key_value == KEY_PREVIEW + "…"


class TestMakeDefault:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_make_default_is_single_and_idempotent(
        self, mock_repo_cls, mock_auth_cls, client, app
    ):
        _seed(app, "first", default=True)
        second_id = _seed(app, "second")
        _mock_auth(
            mock_repo_cls,
            mock_auth_cls,
            make_user_with_permissions(
                "llm.connections.manage", "llm.connections.view"
            ),
        )

        response = client.post(
            f"{BASE}/{second_id}/make-default", headers=_auth_headers()
        )
        assert response.status_code == 200
        assert response.get_json()["connection"]["is_default"] is True

        # Idempotent re-call keeps it the single default.
        client.post(f"{BASE}/{second_id}/make-default", headers=_auth_headers())

        listing = client.get(BASE, headers=_auth_headers()).get_json()["connections"]
        defaults = [row for row in listing if row["is_default"]]
        assert len(defaults) == 1
        assert defaults[0]["slug"] == "second"
        first = next(row for row in listing if row["slug"] == "first")
        assert first["is_default"] is False


class TestBulkActivate:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_bulk_deactivate_clears_default(
        self, mock_repo_cls, mock_auth_cls, client, app
    ):
        conn_id = _seed(app, "to-deactivate", active=True, default=True)
        _mock_auth(
            mock_repo_cls,
            mock_auth_cls,
            make_user_with_permissions(
                "llm.connections.manage", "llm.connections.view"
            ),
        )
        response = client.post(
            f"{BASE}/bulk-activate",
            headers=_auth_headers(),
            json={"ids": [conn_id], "active": False},
        )
        assert response.status_code == 200
        row = response.get_json()["connections"][0]
        assert row["is_active"] is False
        assert row["is_default"] is False


class TestResolveBySlug:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_resolve_by_slug_returns_selected_not_default(
        self, mock_repo_cls, mock_auth_cls, client, app
    ):
        _seed(app, "the-default", default=True, model="claude-3-5-sonnet-latest")
        _seed(app, "openai-one", model="gpt-4o-mini")
        _mock_auth(
            mock_repo_cls,
            mock_auth_cls,
            make_user_with_permissions("llm.connections.view"),
        )
        response = client.get(
            f"{BASE}/resolve?slug=openai-one", headers=_auth_headers()
        )
        assert response.status_code == 200
        assert response.get_json()["connection"]["slug"] == "openai-one"

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_resolve_default_when_no_slug(
        self, mock_repo_cls, mock_auth_cls, client, app
    ):
        _seed(app, "the-default", default=True)
        _seed(app, "other-one", model="gpt-4o-mini")
        _mock_auth(
            mock_repo_cls,
            mock_auth_cls,
            make_user_with_permissions("llm.connections.view"),
        )
        response = client.get(f"{BASE}/resolve", headers=_auth_headers())
        assert response.status_code == 200
        assert response.get_json()["connection"]["slug"] == "the-default"

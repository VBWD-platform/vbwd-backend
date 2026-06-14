"""Unit tests for the admin settings route — S72.4.

The route round-trips the file-backed core settings via the known-key
whitelist. S72.4 adds the ``prices_display_mode`` global netto/brutto toggle:
a valid value persists and is returned on GET; an out-of-enum value is rejected
with HTTP 400 and nothing is persisted.

Auth is mocked the same way as ``test_admin_tax.py``; the settings store is
pointed at a throwaway ``VBWD_VAR_DIR`` so the test never touches real state.
"""
from unittest.mock import patch
from uuid import uuid4

import pytest

from tests.fixtures.access import make_user_with_permissions


def _auth_headers():
    return {"Authorization": "Bearer valid"}


def _mock_auth(mock_repo_cls, mock_auth_cls, user):
    mock_repo_cls.return_value.find_by_id.return_value = user
    mock_auth_cls.return_value.verify_token.return_value = str(uuid4())


@pytest.fixture(autouse=True)
def isolated_var_dir(tmp_path, monkeypatch):
    """Point the settings store at a throwaway ``VBWD_VAR_DIR`` for each test."""
    monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
    return tmp_path


class TestPricesDisplayMode:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_get_returns_prices_display_mode_default(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.view")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        response = client.get("/api/v1/admin/settings", headers=_auth_headers())
        assert response.status_code == 200
        assert response.get_json()["settings"]["prices_display_mode"] == "brutto"

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_put_netto_persists_and_get_returns_it(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.view", "settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        put_response = client.put(
            "/api/v1/admin/settings",
            json={"prices_display_mode": "netto"},
            headers=_auth_headers(),
        )
        assert put_response.status_code == 200
        assert put_response.get_json()["settings"]["prices_display_mode"] == "netto"

        get_response = client.get("/api/v1/admin/settings", headers=_auth_headers())
        assert get_response.status_code == 200
        assert get_response.get_json()["settings"]["prices_display_mode"] == "netto"

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_put_invalid_value_is_rejected_and_not_persisted(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.view", "settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        put_response = client.put(
            "/api/v1/admin/settings",
            json={"prices_display_mode": "gross"},
            headers=_auth_headers(),
        )
        assert put_response.status_code == 400

        get_response = client.get("/api/v1/admin/settings", headers=_auth_headers())
        assert get_response.status_code == 200
        assert get_response.get_json()["settings"]["prices_display_mode"] == "brutto"

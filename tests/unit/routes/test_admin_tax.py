"""Unit tests for admin tax routes — Sprint 15c.

Tests CRUD for tax rates and tax classes via the admin API.
All routes require @require_permission('settings.manage').
"""
from unittest.mock import patch
from uuid import uuid4

from uuid import uuid4 as _uuid4

from tests.fixtures.access import (
    make_user_with_permissions,
    make_user_no_permissions,
)


def _auth_headers():
    return {"Authorization": "Bearer valid"}


def _unique_code(prefix: str = "TAX") -> str:
    """Generate a unique code. Backend may uppercase or lowercase — match prefix case."""
    suffix = _uuid4().hex[:6]
    if prefix == prefix.lower():
        return f"{prefix}_{suffix}"
    return f"{prefix}_{suffix.upper()}"


def _mock_auth(mock_repo_cls, mock_auth_cls, user):
    mock_repo_cls.return_value.find_by_id.return_value = user
    mock_auth_cls.return_value.verify_token.return_value = str(uuid4())


class TestTaxRatePermissions:
    """Tax rate routes require settings.manage permission."""

    def test_list_rates_unauthenticated(self, client):
        response = client.get("/api/v1/admin/tax/rates")
        assert response.status_code == 401

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_rates_forbidden_without_permission(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_no_permissions()
        _mock_auth(mock_repo_cls, mock_auth_cls, user)
        response = client.get(
            "/api/v1/admin/tax/rates", headers=_auth_headers()
        )
        assert response.status_code == 403

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_rates_allowed_with_permission(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)
        response = client.get(
            "/api/v1/admin/tax/rates", headers=_auth_headers()
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "rates" in data


class TestTaxRateCRUD:
    """Tax rate CRUD operations."""

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_rate(self, mock_repo_cls, mock_auth_cls, client):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)
        code = _unique_code("VAT_DE")
        response = client.post(
            "/api/v1/admin/tax/rates",
            json={
                "name": "VAT Germany",
                "code": code,
                "rate": 19.0,
                "country_code": "DE",
                "is_active": True,
                "is_inclusive": False,
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["rate"]["code"] == code
        assert data["rate"]["rate"] == "19.00"

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_rate_missing_name(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)
        response = client.post(
            "/api/v1/admin/tax/rates",
            json={"code": _unique_code("VAT_TEST")},
            headers=_auth_headers(),
        )
        assert response.status_code == 400

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_rate_missing_rate(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)
        response = client.post(
            "/api/v1/admin/tax/rates",
            json={"name": "Test", "code": _unique_code("TEST")},
            headers=_auth_headers(),
        )
        assert response.status_code == 400

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_and_get_rate(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        code = _unique_code("VAT_FR")
        create_response = client.post(
            "/api/v1/admin/tax/rates",
            json={
                "name": "VAT France",
                "code": code,
                "rate": 20.0,
                "country_code": "FR",
            },
            headers=_auth_headers(),
        )
        assert create_response.status_code == 201
        rate_id = create_response.get_json()["rate"]["id"]

        get_response = client.get(
            f"/api/v1/admin/tax/rates/{rate_id}",
            headers=_auth_headers(),
        )
        assert get_response.status_code == 200
        assert get_response.get_json()["rate"]["code"] == code

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_update_rate(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        code = _unique_code("VAT_AT")
        create_response = client.post(
            "/api/v1/admin/tax/rates",
            json={
                "name": "VAT Austria",
                "code": code,
                "rate": 20.0,
                "country_code": "AT",
            },
            headers=_auth_headers(),
        )
        rate_id = create_response.get_json()["rate"]["id"]

        update_response = client.put(
            f"/api/v1/admin/tax/rates/{rate_id}",
            json={"rate": 21.0, "name": "VAT Austria Updated"},
            headers=_auth_headers(),
        )
        assert update_response.status_code == 200
        assert update_response.get_json()["rate"]["rate"] == "21.00"

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_delete_rate(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        code = _unique_code("VAT_DEL")
        create_response = client.post(
            "/api/v1/admin/tax/rates",
            json={
                "name": "VAT Delete",
                "code": code,
                "rate": 15.0,
            },
            headers=_auth_headers(),
        )
        rate_id = create_response.get_json()["rate"]["id"]

        delete_response = client.delete(
            f"/api/v1/admin/tax/rates/{rate_id}",
            headers=_auth_headers(),
        )
        assert delete_response.status_code == 200

        get_response = client.get(
            f"/api/v1/admin/tax/rates/{rate_id}",
            headers=_auth_headers(),
        )
        assert get_response.status_code == 404

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_duplicate_code_rejected(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        code = _unique_code("VAT_DUP")
        client.post(
            "/api/v1/admin/tax/rates",
            json={
                "name": "VAT Dup",
                "code": code,
                "rate": 10.0,
            },
            headers=_auth_headers(),
        )
        response = client.post(
            "/api/v1/admin/tax/rates",
            json={
                "name": "VAT Dup Again",
                "code": code,
                "rate": 12.0,
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 400
        assert "already exists" in response.get_json()["error"]

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_filter_by_country(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        code_es = _unique_code("VAT_ES")
        code_it = _unique_code("VAT_IT")
        client.post(
            "/api/v1/admin/tax/rates",
            json={
                "name": "VAT ES",
                "code": code_es,
                "rate": 21.0,
                "country_code": "ES",
            },
            headers=_auth_headers(),
        )
        client.post(
            "/api/v1/admin/tax/rates",
            json={
                "name": "VAT IT",
                "code": code_it,
                "rate": 22.0,
                "country_code": "IT",
            },
            headers=_auth_headers(),
        )
        response = client.get(
            "/api/v1/admin/tax/rates?country=ES",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        rates = response.get_json()["rates"]
        assert all(r["country_code"] == "ES" for r in rates)


class TestTaxClassCRUD:
    """Tax class CRUD operations."""

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_class(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        class_code = _unique_code("cls")
        response = client.post(
            "/api/v1/admin/tax/classes",
            json={
                "name": "Standard",
                "code": class_code,
                "description": "Standard tax rate",
                "default_rate": 19.0,
                "is_default": True,
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["tax_class"]["code"] == class_code
        assert data["tax_class"]["is_default"] is True

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_classes(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        class_code = _unique_code("cls")
        client.post(
            "/api/v1/admin/tax/classes",
            json={
                "name": "Zero Rate",
                "code": class_code,
                "default_rate": 0,
            },
            headers=_auth_headers(),
        )
        response = client.get(
            "/api/v1/admin/tax/classes",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert "classes" in response.get_json()

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_update_class(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        class_code = _unique_code("cls")
        create_response = client.post(
            "/api/v1/admin/tax/classes",
            json={
                "name": "Reduced",
                "code": class_code,
                "default_rate": 7.0,
            },
            headers=_auth_headers(),
        )
        class_id = create_response.get_json()["tax_class"]["id"]

        update_response = client.put(
            f"/api/v1/admin/tax/classes/{class_id}",
            json={"default_rate": 8.0},
            headers=_auth_headers(),
        )
        assert update_response.status_code == 200
        assert (
            update_response.get_json()["tax_class"]["default_rate"]
            == "8.00"
        )

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_delete_class(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        class_code = _unique_code("cls")
        create_response = client.post(
            "/api/v1/admin/tax/classes",
            json={
                "name": "Luxury",
                "code": class_code,
                "default_rate": 25.0,
            },
            headers=_auth_headers(),
        )
        class_id = create_response.get_json()["tax_class"]["id"]

        delete_response = client.delete(
            f"/api/v1/admin/tax/classes/{class_id}",
            headers=_auth_headers(),
        )
        assert delete_response.status_code == 200

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_duplicate_class_code_rejected(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        class_code = _unique_code("cls")
        client.post(
            "/api/v1/admin/tax/classes",
            json={
                "name": "Dup Class",
                "code": class_code,
                "default_rate": 5.0,
            },
            headers=_auth_headers(),
        )
        response = client.post(
            "/api/v1/admin/tax/classes",
            json={
                "name": "Dup Class Again",
                "code": class_code,
                "default_rate": 10.0,
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 400
        assert "already exists" in response.get_json()["error"]

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_setting_default_unsets_previous(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        class_code_first = _unique_code("cls")
        class_code_second = _unique_code("cls")
        first_response = client.post(
            "/api/v1/admin/tax/classes",
            json={
                "name": "First Default",
                "code": class_code_first,
                "default_rate": 19.0,
                "is_default": True,
            },
            headers=_auth_headers(),
        )
        first_id = first_response.get_json()["tax_class"]["id"]

        client.post(
            "/api/v1/admin/tax/classes",
            json={
                "name": "Second Default",
                "code": class_code_second,
                "default_rate": 20.0,
                "is_default": True,
            },
            headers=_auth_headers(),
        )

        # First one should no longer be default
        response = client.get(
            "/api/v1/admin/tax/classes",
            headers=_auth_headers(),
        )
        classes = response.get_json()["classes"]
        first_class = next(
            (c for c in classes if c["id"] == first_id), None
        )
        if first_class:
            assert first_class["is_default"] is False


class TestTaxRateWithClass:
    """Tax rate linked to tax class."""

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_rate_with_class(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        class_code = _unique_code("cls")
        code = _unique_code("VAT_DE")
        class_response = client.post(
            "/api/v1/admin/tax/classes",
            json={
                "name": "Standard Linked",
                "code": class_code,
                "default_rate": 19.0,
            },
            headers=_auth_headers(),
        )
        class_id = class_response.get_json()["tax_class"]["id"]

        rate_response = client.post(
            "/api/v1/admin/tax/rates",
            json={
                "name": "VAT DE Linked",
                "code": code,
                "rate": 19.0,
                "country_code": "DE",
                "tax_class_id": class_id,
            },
            headers=_auth_headers(),
        )
        assert rate_response.status_code == 201
        assert (
            rate_response.get_json()["rate"]["tax_class_id"]
            == class_id
        )

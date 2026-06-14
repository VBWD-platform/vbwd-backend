"""Unit tests for admin tax routes — Sprint 15c (S72.3 flatten).

Tests CRUD for tax rates via the admin API. The ``TaxClass`` model was
flattened into a denormalized ``tax_class`` string on ``Tax``; the class CRUD
routes are gone and a tax carries ``tax_class`` (a plain label) in/out.
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
        response = client.get("/api/v1/admin/tax/rates", headers=_auth_headers())
        assert response.status_code == 403

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_rates_allowed_with_permission(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)
        response = client.get("/api/v1/admin/tax/rates", headers=_auth_headers())
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
    def test_create_rate_missing_name(self, mock_repo_cls, mock_auth_cls, client):
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
    def test_create_rate_missing_rate(self, mock_repo_cls, mock_auth_cls, client):
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
    def test_create_and_get_rate(self, mock_repo_cls, mock_auth_cls, client):
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
    def test_update_rate(self, mock_repo_cls, mock_auth_cls, client):
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
    def test_delete_rate(self, mock_repo_cls, mock_auth_cls, client):
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
    def test_delete_in_use_rate_returns_409_not_500(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        """An in-use tax (FK RESTRICT from a *_tax join table) → 409, not 500."""
        from sqlalchemy.exc import IntegrityError

        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        code = _unique_code("VAT_INUSE")
        rate_id = client.post(
            "/api/v1/admin/tax/rates",
            json={"name": "In Use", "code": code, "rate": 10.0},
            headers=_auth_headers(),
        ).get_json()["rate"]["id"]

        # Simulate the ON DELETE RESTRICT FK violation on commit.
        with patch(
            "vbwd.routes.admin.tax.db.session.commit",
            side_effect=IntegrityError("DELETE", {}, Exception("fk")),
        ):
            resp = client.delete(
                f"/api/v1/admin/tax/rates/{rate_id}",
                headers=_auth_headers(),
            )

        assert resp.status_code == 409
        assert "in use" in resp.get_json()["error"].lower()
        # Rolled back — the tax still exists.
        assert (
            client.get(
                f"/api/v1/admin/tax/rates/{rate_id}", headers=_auth_headers()
            ).status_code
            == 200
        )

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_duplicate_code_rejected(self, mock_repo_cls, mock_auth_cls, client):
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
    def test_filter_by_country(self, mock_repo_cls, mock_auth_cls, client):
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

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_filter_by_tax_class(self, mock_repo_cls, mock_auth_cls, client):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        code_std = _unique_code("VAT_STD")
        code_red = _unique_code("VAT_RED")
        client.post(
            "/api/v1/admin/tax/rates",
            json={
                "name": "VAT Standard",
                "code": code_std,
                "rate": 19.0,
                "tax_class": "standard",
            },
            headers=_auth_headers(),
        )
        client.post(
            "/api/v1/admin/tax/rates",
            json={
                "name": "VAT Reduced",
                "code": code_red,
                "rate": 7.0,
                "tax_class": "reduced",
            },
            headers=_auth_headers(),
        )
        response = client.get(
            "/api/v1/admin/tax/rates?tax_class=standard",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        rates = response.get_json()["rates"]
        assert all(r["tax_class"] == "standard" for r in rates)
        assert any(r["code"] == code_std for r in rates)
        assert not any(r["code"] == code_red for r in rates)


class TestTaxRateWithTaxClassLabel:
    """Tax rate carries a denormalized ``tax_class`` string (S72.3 flatten)."""

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_rate_with_tax_class(self, mock_repo_cls, mock_auth_cls, client):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        code = _unique_code("VAT_DE")
        rate_response = client.post(
            "/api/v1/admin/tax/rates",
            json={
                "name": "VAT DE Labelled",
                "code": code,
                "rate": 19.0,
                "country_code": "DE",
                "tax_class": "standard",
            },
            headers=_auth_headers(),
        )
        assert rate_response.status_code == 201
        body = rate_response.get_json()["rate"]
        assert body["tax_class"] == "standard"
        assert "tax_class_id" not in body

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_update_rate_sets_tax_class(self, mock_repo_cls, mock_auth_cls, client):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        code = _unique_code("VAT_UPD")
        create_response = client.post(
            "/api/v1/admin/tax/rates",
            json={"name": "VAT Upd", "code": code, "rate": 19.0},
            headers=_auth_headers(),
        )
        rate_id = create_response.get_json()["rate"]["id"]

        update_response = client.put(
            f"/api/v1/admin/tax/rates/{rate_id}",
            json={"tax_class": "reduced"},
            headers=_auth_headers(),
        )
        assert update_response.status_code == 200
        assert update_response.get_json()["rate"]["tax_class"] == "reduced"


class TestTaxClassRoutesGone:
    """The flattened ``TaxClass`` model has no CRUD routes anymore."""

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_classes_route_gone(self, mock_repo_cls, mock_auth_cls, client):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)
        response = client.get("/api/v1/admin/tax/classes", headers=_auth_headers())
        assert response.status_code == 404

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_class_route_gone(self, mock_repo_cls, mock_auth_cls, client):
        user = make_user_with_permissions("settings.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)
        response = client.post(
            "/api/v1/admin/tax/classes",
            json={"name": "Standard", "code": "standard", "default_rate": 19.0},
            headers=_auth_headers(),
        )
        assert response.status_code == 404

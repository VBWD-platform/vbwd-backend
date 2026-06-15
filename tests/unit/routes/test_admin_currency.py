"""Unit tests for the admin currency routes (S84).

DB-backed (like ``test_admin_tax``): hits the live catalog through the
``client`` fixture, with mocked auth. The active set + default live in the
core settings JSON; each test points ``VBWD_VAR_DIR`` at a throwaway dir so
settings are isolated and never clobber the running stack's file.
"""
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from tests.fixtures.access import (
    make_user_with_permissions,
    make_user_no_permissions,
)


def _auth_headers():
    return {"Authorization": "Bearer valid"}


def _mock_auth(mock_repo_cls, mock_auth_cls, user):
    mock_repo_cls.return_value.find_by_id.return_value = user
    mock_auth_cls.return_value.verify_token.return_value = str(uuid4())


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch, app):
    """Throwaway VBWD_VAR_DIR + a known active set/default for each test.

    The known active set (``["EUR", "USD"]``) is validated against the live
    catalog, so both rows must exist before the update — ensure them here
    (idempotent) the same way ``seeded_gbp`` ensures GBP.
    """
    monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
    from vbwd.extensions import db
    from vbwd.models.currency import Currency
    from vbwd.services.core_settings_store import update_core_settings

    catalog = {
        "EUR": ("Euro", "€", Decimal("1.0")),
        "USD": ("US Dollar", "$", Decimal("1.08")),
    }
    with app.app_context():
        for code, (name, symbol, rate) in catalog.items():
            existing = db.session.query(Currency).filter_by(code=code).first()
            if not existing:
                db.session.add(
                    Currency(
                        id=uuid4(),
                        code=code,
                        name=name,
                        symbol=symbol,
                        exchange_rate=rate,
                        decimal_places=2,
                    )
                )
        db.session.commit()

        update_core_settings(
            {"active_currencies": ["EUR", "USD"], "default_currency": "EUR"}
        )
    return tmp_path


@pytest.fixture
def seeded_gbp(app):
    """Ensure a GBP catalog row exists (idempotent), 0.85 per EUR."""
    from vbwd.extensions import db
    from vbwd.models.currency import Currency

    with app.app_context():
        gbp = db.session.query(Currency).filter_by(code="GBP").first()
        if not gbp:
            db.session.add(
                Currency(
                    id=uuid4(),
                    code="GBP",
                    name="Pound",
                    symbol="£",
                    exchange_rate=Decimal("0.85"),
                    decimal_places=2,
                )
            )
            db.session.commit()
    yield


# ── Permission gating ──────────────────────────────────────────────────────


class TestPermissions:
    def test_list_unauthenticated(self, client):
        response = client.get("/api/v1/admin/currencies")
        assert response.status_code == 401

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_forbidden_without_permission(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _mock_auth(mock_repo_cls, mock_auth_cls, make_user_no_permissions())
        response = client.get("/api/v1/admin/currencies", headers=_auth_headers())
        assert response.status_code == 403

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_activate_forbidden_without_manage(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        # settings.view is NOT enough to mutate.
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.view")
        )
        response = client.post(
            "/api/v1/admin/currencies/USD/activate", headers=_auth_headers()
        )
        assert response.status_code == 403


# ── GET ────────────────────────────────────────────────────────────────────


class TestListCurrencies:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_get_derives_flags_from_settings(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.view")
        )
        response = client.get("/api/v1/admin/currencies", headers=_auth_headers())
        assert response.status_code == 200
        rows = response.get_json()["currencies"]
        by_code = {row["code"]: row for row in rows}
        assert by_code["EUR"]["is_default"] is True
        assert by_code["EUR"]["is_active"] is True
        assert by_code["USD"]["is_active"] is True
        assert by_code["USD"]["is_default"] is False
        # No is_active/is_default columns leak — flags are computed.
        assert "decimal_places" in by_code["EUR"]

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_get_sorts_active_first(
        self, mock_repo_cls, mock_auth_cls, client, seeded_gbp
    ):
        from vbwd.services.core_settings_store import update_core_settings

        # GBP exists in the catalog but is NOT active → must sort after actives.
        update_core_settings(
            {"active_currencies": ["EUR", "USD"], "default_currency": "EUR"}
        )
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.view")
        )
        response = client.get("/api/v1/admin/currencies", headers=_auth_headers())
        rows = response.get_json()["currencies"]
        active_flags = [row["is_active"] for row in rows]
        # All actives come before any inactive.
        assert active_flags == sorted(active_flags, reverse=True)


# ── activate / deactivate ───────────────────────────────────────────────────


class TestActivateDeactivate:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_activate_adds_to_settings(
        self, mock_repo_cls, mock_auth_cls, client, seeded_gbp
    ):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.post(
            "/api/v1/admin/currencies/GBP/activate", headers=_auth_headers()
        )
        assert response.status_code == 200
        rows = {r["code"]: r for r in response.get_json()["currencies"]}
        assert rows["GBP"]["is_active"] is True

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_activate_unknown_returns_404(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.post(
            "/api/v1/admin/currencies/XYZ/activate", headers=_auth_headers()
        )
        assert response.status_code == 404

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_deactivate_default_returns_400(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.post(
            "/api/v1/admin/currencies/EUR/deactivate", headers=_auth_headers()
        )
        assert response.status_code == 400

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_deactivate_unknown_returns_404(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.post(
            "/api/v1/admin/currencies/XYZ/deactivate", headers=_auth_headers()
        )
        assert response.status_code == 404

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_deactivate_active_removes_from_settings(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.post(
            "/api/v1/admin/currencies/USD/deactivate", headers=_auth_headers()
        )
        assert response.status_code == 200
        rows = {r["code"]: r for r in response.get_json()["currencies"]}
        assert rows["USD"]["is_active"] is False


# ── set-default ─────────────────────────────────────────────────────────────


class TestSetDefault:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_set_default_active_rebases(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.post(
            "/api/v1/admin/currencies/USD/set-default", headers=_auth_headers()
        )
        assert response.status_code == 200
        rows = {r["code"]: r for r in response.get_json()["currencies"]}
        assert rows["USD"]["is_default"] is True
        assert Decimal(rows["USD"]["exchange_rate"]) == Decimal("1")
        # EUR re-based to 1 / 1.08.
        expected_eur = Decimal("1.0") / Decimal("1.08")
        assert abs(Decimal(rows["EUR"]["exchange_rate"]) - expected_eur) < Decimal(
            "1e-7"
        )
        # Restore EUR default so the shared catalog is left re-based-back.
        client.post("/api/v1/admin/currencies/EUR/set-default", headers=_auth_headers())

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_set_default_inactive_returns_400(
        self, mock_repo_cls, mock_auth_cls, client, seeded_gbp
    ):
        from vbwd.services.core_settings_store import update_core_settings

        update_core_settings(
            {"active_currencies": ["EUR", "USD"], "default_currency": "EUR"}
        )
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        # GBP is in the catalog but not active.
        response = client.post(
            "/api/v1/admin/currencies/GBP/set-default", headers=_auth_headers()
        )
        assert response.status_code == 400

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_set_default_unknown_returns_404(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.post(
            "/api/v1/admin/currencies/XYZ/set-default", headers=_auth_headers()
        )
        assert response.status_code == 404


# ── create (POST) ───────────────────────────────────────────────────────────


@pytest.fixture
def cleanup_created(app):
    """Remove any currency rows created by a test (keep the catalog stable)."""
    created_codes: list[str] = []
    yield created_codes
    from vbwd.extensions import db
    from vbwd.models.currency import Currency

    with app.app_context():
        for code in created_codes:
            row = db.session.query(Currency).filter_by(code=code).first()
            if row:
                db.session.delete(row)
        db.session.commit()


class TestCreateCurrency:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_forbidden_without_manage(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.view")
        )
        response = client.post(
            "/api/v1/admin/currencies",
            json={"code": "CHF", "name": "Franc", "symbol": "Fr"},
            headers=_auth_headers(),
        )
        assert response.status_code == 403

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_happy_returns_201(
        self, mock_repo_cls, mock_auth_cls, client, cleanup_created
    ):
        cleanup_created.append("CHF")
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.post(
            "/api/v1/admin/currencies",
            json={
                "code": "CHF",
                "name": "Franc",
                "symbol": "Fr",
                "exchange_rate": 0.95,
                "decimal_places": 2,
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        body = response.get_json()["currency"]
        assert body["code"] == "CHF"
        assert body["name"] == "Franc"
        assert Decimal(body["exchange_rate"]) == Decimal("0.95")

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_created_currency_is_inactive(
        self, mock_repo_cls, mock_auth_cls, client, cleanup_created
    ):
        cleanup_created.append("CHF")
        _mock_auth(
            mock_repo_cls,
            mock_auth_cls,
            make_user_with_permissions("settings.manage", "settings.view"),
        )
        client.post(
            "/api/v1/admin/currencies",
            json={"code": "CHF", "name": "Franc", "symbol": "Fr"},
            headers=_auth_headers(),
        )
        listing = client.get("/api/v1/admin/currencies", headers=_auth_headers())
        rows = {r["code"]: r for r in listing.get_json()["currencies"]}
        assert rows["CHF"]["is_active"] is False
        assert rows["CHF"]["is_default"] is False

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_duplicate_returns_400(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.post(
            "/api/v1/admin/currencies",
            json={"code": "USD", "name": "Dollar", "symbol": "$"},
            headers=_auth_headers(),
        )
        assert response.status_code == 400
        assert "error" in response.get_json()

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_invalid_code_returns_400(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.post(
            "/api/v1/admin/currencies",
            json={"code": "US", "name": "Dollar", "symbol": "$"},
            headers=_auth_headers(),
        )
        assert response.status_code == 400

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_non_positive_rate_returns_400(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.post(
            "/api/v1/admin/currencies",
            json={"code": "CHF", "name": "Franc", "symbol": "Fr", "exchange_rate": 0},
            headers=_auth_headers(),
        )
        assert response.status_code == 400

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_missing_required_returns_400(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.post(
            "/api/v1/admin/currencies",
            json={"code": "CHF", "name": "Franc"},
            headers=_auth_headers(),
        )
        assert response.status_code == 400


# ── delete (DELETE) ─────────────────────────────────────────────────────────


class TestDeleteCurrency:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_delete_forbidden_without_manage(
        self, mock_repo_cls, mock_auth_cls, client, seeded_gbp
    ):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.view")
        )
        response = client.delete(
            "/api/v1/admin/currencies/GBP", headers=_auth_headers()
        )
        assert response.status_code == 403

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_delete_inactive_returns_200_with_catalog(
        self, mock_repo_cls, mock_auth_cls, client, seeded_gbp
    ):
        from vbwd.services.core_settings_store import update_core_settings

        # GBP exists but is inactive (not in active set, not default).
        update_core_settings(
            {"active_currencies": ["EUR", "USD"], "default_currency": "EUR"}
        )
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.delete(
            "/api/v1/admin/currencies/GBP", headers=_auth_headers()
        )
        assert response.status_code == 200
        rows = {r["code"]: r for r in response.get_json()["currencies"]}
        assert "GBP" not in rows

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_delete_active_returns_400(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        # USD is active.
        response = client.delete(
            "/api/v1/admin/currencies/USD", headers=_auth_headers()
        )
        assert response.status_code == 400

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_delete_default_returns_400(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        # EUR is the default.
        response = client.delete(
            "/api/v1/admin/currencies/EUR", headers=_auth_headers()
        )
        assert response.status_code == 400

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_delete_unknown_returns_404(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.delete(
            "/api/v1/admin/currencies/XYZ", headers=_auth_headers()
        )
        assert response.status_code == 404


# ── rate PUT ────────────────────────────────────────────────────────────────


class TestUpdateRate:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_update_rate_happy(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.put(
            "/api/v1/admin/currencies/USD/rate",
            json={"exchange_rate": 1.1},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        body = response.get_json()["currency"]
        assert body["code"] == "USD"
        assert Decimal(body["exchange_rate"]) == Decimal("1.1")
        # Restore the seeded 1.08 so the shared catalog is unchanged.
        client.put(
            "/api/v1/admin/currencies/USD/rate",
            json={"exchange_rate": 1.08},
            headers=_auth_headers(),
        )

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_update_default_rate_returns_400(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.put(
            "/api/v1/admin/currencies/EUR/rate",
            json={"exchange_rate": 2.0},
            headers=_auth_headers(),
        )
        assert response.status_code == 400

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_update_rate_non_positive_returns_400(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.put(
            "/api/v1/admin/currencies/USD/rate",
            json={"exchange_rate": 0},
            headers=_auth_headers(),
        )
        assert response.status_code == 400

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_update_rate_unknown_returns_404(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.put(
            "/api/v1/admin/currencies/XYZ/rate",
            json={"exchange_rate": 1.0},
            headers=_auth_headers(),
        )
        assert response.status_code == 404

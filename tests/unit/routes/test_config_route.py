"""Unit tests for the public config route (``/api/v1/config``).

S93 Slice A: the public config endpoint exposes the global operating currency
and the price-display modes so the frontend has a single, auth-free source of
truth for the checkout currency. The values come straight from the file-backed
core settings store (``default_currency``, ``prices_display_mode``,
``prices_mode_in_db``).

The settings store is pointed at a throwaway ``VBWD_VAR_DIR`` so the test never
touches real state; no auth is required (this is a public endpoint).
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_var_dir(tmp_path, monkeypatch):
    """Point the settings store at a throwaway ``VBWD_VAR_DIR`` for each test."""
    monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
    return tmp_path


class TestPublicConfig:
    def test_returns_default_currency_and_modes(self, client):
        response = client.get("/api/v1/config")
        assert response.status_code == 200
        body = response.get_json()
        assert body["default_currency"] == "EUR"
        assert body["prices_display_mode"] == "brutto"
        assert body["prices_mode_in_db"] == "NETTO"

    def test_reflects_updated_settings(self, client):
        from vbwd.services.core_settings_store import update_core_settings

        update_core_settings({"prices_display_mode": "netto"})

        response = client.get("/api/v1/config")
        assert response.status_code == 200
        body = response.get_json()
        assert body["prices_display_mode"] == "netto"

    def test_includes_default_site_name(self, client):
        response = client.get("/api/v1/config")
        assert response.status_code == 200
        body = response.get_json()
        # White-label brand name defaults to an empty string (fe applies its
        # own "VBWD" display fallback).
        assert body["site_name"] == ""

    def test_reflects_saved_site_name(self, client):
        from vbwd.services.core_settings_store import update_core_settings

        update_core_settings({"site_name": "Acme"})

        response = client.get("/api/v1/config")
        assert response.status_code == 200
        body = response.get_json()
        assert body["site_name"] == "Acme"

    def test_requires_no_authentication(self, client):
        # No Authorization header — a public read must still succeed.
        response = client.get("/api/v1/config")
        assert response.status_code == 200

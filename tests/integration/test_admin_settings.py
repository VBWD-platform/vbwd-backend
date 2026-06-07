"""S57 — integration tests for the file-backed core settings API.

Exercises the live ``/api/v1/admin/settings`` endpoints against the running
backend (same convention as ``test_admin_payment_methods.py``):

- ``PUT`` then ``GET`` returns the saved values (durable across requests, i.e.
  across gunicorn workers — the file under ``VBWD_VAR_DIR`` is the single
  source of truth, not per-worker memory).
- a second ``GET`` still returns the value (multi-worker / multi-read
  consistency).
- unknown keys are ignored (known-key whitelist).
- ``settings.view`` / ``settings.manage`` gating (401 without auth,
  403 without permission).
"""
import os
from uuid import uuid4

import pytest
import requests


class TestAdminSettings:
    BASE_URL = os.getenv("API_BASE_URL", "http://localhost:5000/api/v1")

    @pytest.fixture(autouse=True)
    def setup(self):
        try:
            response = requests.get(f"{self.BASE_URL}/health", timeout=5)
            if response.status_code != 200:
                pytest.skip("Backend not healthy, skipping integration tests")
        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not reachable, skipping integration tests")

    @pytest.fixture
    def admin_headers(self) -> dict:
        credentials = {
            "email": os.getenv("TEST_ADMIN_EMAIL", "admin@example.com"),
            "password": os.getenv("TEST_ADMIN_PASSWORD", "AdminPass123@"),
        }
        response = requests.post(
            f"{self.BASE_URL}/auth/login", json=credentials, timeout=10
        )
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        return {"Authorization": f"Bearer {response.json().get('token')}"}

    @pytest.fixture
    def user_headers(self) -> dict:
        credentials = {
            "email": os.getenv("TEST_USER_EMAIL", "test@example.com"),
            "password": os.getenv("TEST_USER_PASSWORD", "TestPass123@"),
        }
        response = requests.post(
            f"{self.BASE_URL}/auth/login", json=credentials, timeout=10
        )
        assert response.status_code == 200, f"User login failed: {response.text}"
        return {"Authorization": f"Bearer {response.json().get('token')}"}

    # ---- Auth gating -----------------------------------------------------

    def test_get_requires_auth(self):
        response = requests.get(f"{self.BASE_URL}/admin/settings", timeout=5)
        assert response.status_code == 401

    def test_put_requires_auth(self):
        response = requests.put(
            f"{self.BASE_URL}/admin/settings",
            json={"provider_name": "x"},
            timeout=5,
        )
        assert response.status_code == 401

    def test_get_requires_permission(self, user_headers):
        response = requests.get(
            f"{self.BASE_URL}/admin/settings", headers=user_headers, timeout=5
        )
        assert response.status_code == 403

    def test_put_requires_permission(self, user_headers):
        response = requests.put(
            f"{self.BASE_URL}/admin/settings",
            json={"provider_name": "x"},
            headers=user_headers,
            timeout=5,
        )
        assert response.status_code == 403

    # ---- Shape -----------------------------------------------------------

    def test_get_returns_settings_object(self, admin_headers):
        response = requests.get(
            f"{self.BASE_URL}/admin/settings", headers=admin_headers, timeout=5
        )
        assert response.status_code == 200
        data = response.json()
        assert "settings" in data
        assert "provider_name" in data["settings"]
        assert "bank_iban" in data["settings"]

    # ---- Persistence + consistency --------------------------------------

    def test_put_then_get_returns_saved_values(self, admin_headers):
        provider_name = f"Provider {uuid4().hex[:8]}"
        contact_email = f"{uuid4().hex[:8]}@example.com"

        put_response = requests.put(
            f"{self.BASE_URL}/admin/settings",
            json={"provider_name": provider_name, "contact_email": contact_email},
            headers=admin_headers,
            timeout=10,
        )
        assert put_response.status_code == 200
        put_data = put_response.json()
        assert put_data["settings"]["provider_name"] == provider_name
        assert put_data["message"] == "Settings updated successfully"

        get_response = requests.get(
            f"{self.BASE_URL}/admin/settings", headers=admin_headers, timeout=5
        )
        assert get_response.status_code == 200
        assert get_response.json()["settings"]["provider_name"] == provider_name
        assert get_response.json()["settings"]["contact_email"] == contact_email

    def test_value_survives_repeated_reads(self, admin_headers):
        """A second/third read returns the same value (file is the source of
        truth shared by all workers, not per-worker memory)."""
        bank_name = f"Bank {uuid4().hex[:8]}"
        requests.put(
            f"{self.BASE_URL}/admin/settings",
            json={"bank_name": bank_name},
            headers=admin_headers,
            timeout=10,
        )
        for _ in range(3):
            response = requests.get(
                f"{self.BASE_URL}/admin/settings", headers=admin_headers, timeout=5
            )
            assert response.status_code == 200
            assert response.json()["settings"]["bank_name"] == bank_name

    def test_unknown_keys_are_ignored(self, admin_headers):
        response = requests.put(
            f"{self.BASE_URL}/admin/settings",
            json={"provider_name": "Known", "totally_unknown_key": "nope"},
            headers=admin_headers,
            timeout=10,
        )
        assert response.status_code == 200
        assert "totally_unknown_key" not in response.json()["settings"]

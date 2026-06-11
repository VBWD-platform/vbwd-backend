"""S52.4 — live integration tests for the core API-key routes.

Admin CRUD over any user's keys (plaintext once, revoke flips ``is_active``,
delete removes) and the self-service gate (401 without auth, 403 without the
``manage_api`` permission). Owner-isolation + grantable-scope rules are covered
by unit tests.
"""
import os

import pytest
import requests


class TestApiKeysRoutes:
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
    def user_login(self) -> dict:
        credentials = {
            "email": os.getenv("TEST_USER_EMAIL", "test@example.com"),
            "password": os.getenv("TEST_USER_PASSWORD", "TestPass123@"),
        }
        response = requests.post(
            f"{self.BASE_URL}/auth/login", json=credentials, timeout=10
        )
        assert response.status_code == 200, f"User login failed: {response.text}"
        return response.json()

    def _target_user_id(self, admin_headers) -> str:
        response = requests.get(
            f"{self.BASE_URL}/admin/users/", headers=admin_headers, timeout=10
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        users = payload.get("users") or payload.get("data") or payload
        assert users, "No users returned"
        return str(users[0]["id"])

    # ---- scopes endpoint -------------------------------------------------

    def test_admin_scopes_requires_auth(self):
        response = requests.get(f"{self.BASE_URL}/admin/api-keys/scopes", timeout=5)
        assert response.status_code == 401

    def test_admin_scopes_returns_catalogue(self, admin_headers):
        response = requests.get(
            f"{self.BASE_URL}/admin/api-keys/scopes",
            headers=admin_headers,
            timeout=5,
        )
        assert response.status_code == 200
        assert "core" in response.json()["scopes"]

    # ---- admin CRUD ------------------------------------------------------

    def test_admin_create_list_revoke_delete_cycle(self, admin_headers):
        user_id = self._target_user_id(admin_headers)

        created = requests.post(
            f"{self.BASE_URL}/admin/users/{user_id}/api-keys",
            json={"label": "S52 admin test", "scopes": [], "ip_whitelist": []},
            headers=admin_headers,
            timeout=10,
        )
        assert created.status_code == 201, created.text
        body = created.json()["api_key"]
        key_id = body["id"]
        # Plaintext returned exactly once, never the hash.
        assert body["plaintext"].startswith("vbwdk_")
        assert "key_hash" not in body
        assert body["is_active"] is True

        listed = requests.get(
            f"{self.BASE_URL}/admin/users/{user_id}/api-keys",
            headers=admin_headers,
            timeout=10,
        )
        assert listed.status_code == 200
        ids = [k["id"] for k in listed.json()["api_keys"]]
        assert key_id in ids
        # A subsequent list never re-exposes the plaintext.
        for key in listed.json()["api_keys"]:
            assert "plaintext" not in key

        revoked = requests.post(
            f"{self.BASE_URL}/admin/api-keys/{key_id}/revoke",
            headers=admin_headers,
            timeout=10,
        )
        assert revoked.status_code == 200
        listed_after = requests.get(
            f"{self.BASE_URL}/admin/users/{user_id}/api-keys",
            headers=admin_headers,
            timeout=10,
        )
        revoked_row = next(
            k for k in listed_after.json()["api_keys"] if k["id"] == key_id
        )
        assert revoked_row["is_active"] is False

        deleted = requests.delete(
            f"{self.BASE_URL}/admin/api-keys/{key_id}",
            headers=admin_headers,
            timeout=10,
        )
        assert deleted.status_code == 200
        listed_final = requests.get(
            f"{self.BASE_URL}/admin/users/{user_id}/api-keys",
            headers=admin_headers,
            timeout=10,
        )
        assert key_id not in [k["id"] for k in listed_final.json()["api_keys"]]

    # ---- self-service gating --------------------------------------------

    def test_self_service_list_requires_auth(self):
        response = requests.get(f"{self.BASE_URL}/api-keys", timeout=5)
        assert response.status_code == 401

    def test_self_service_create_requires_manage_api(self, user_login):
        headers = {"Authorization": f"Bearer {user_login['token']}"}
        response = requests.post(
            f"{self.BASE_URL}/api-keys",
            json={"label": "x", "scopes": []},
            headers=headers,
            timeout=10,
        )
        # The seeded test user has no manage_api permission → 403.
        assert response.status_code == 403

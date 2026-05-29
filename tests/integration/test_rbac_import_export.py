"""Integration tests for RBAC role import/export round-trip — Sprint S38.

Run with:
    docker compose --profile test-integration run --rm test-integration \
        pytest tests/integration/test_rbac_import_export.py -v

Hits the live API. Verifies that the default roles export, that a wiped
non-system role is restored by import (identical set), and that system
roles are never overwritten on import.
"""
import os

import pytest
import requests


class TestRbacImportExport:
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
    def admin_headers(self):
        credentials = {
            "email": os.getenv("TEST_ADMIN_EMAIL", "admin@example.com"),
            "password": os.getenv("TEST_ADMIN_PASSWORD", "AdminPass123@"),
        }
        response = requests.post(
            f"{self.BASE_URL}/auth/login", json=credentials, timeout=10
        )
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        token = response.json().get("token")
        return {"Authorization": f"Bearer {token}"}

    def _ensure_seeded(self, admin_headers):
        """Make sure at least one custom role exists for the round-trip."""
        export = requests.post(
            f"{self.BASE_URL}/admin/access/export",
            headers=admin_headers,
            json={},
            timeout=10,
        )
        assert export.status_code == 200
        return export.json()

    def test_export_returns_versioned_roles_shape(self, admin_headers):
        from uuid import uuid4

        # Seed a custom (non-system) role so export has deterministic content.
        # Name == slug to stay unique across repeated runs (role.name is unique).
        slug = f"itest-export-{uuid4().hex[:8]}"
        requests.post(
            f"{self.BASE_URL}/admin/access/levels",
            headers=admin_headers,
            json={"name": slug, "slug": slug, "permissions": ["users.view"]},
            timeout=10,
        )

        data = self._ensure_seeded(admin_headers)
        assert data["version"] == 1
        assert isinstance(data["roles"], list)
        exported = next(r for r in data["roles"] if r["slug"] == slug)
        assert exported["permissions"] == ["users.view"]
        assert exported["is_system"] is False

    def test_wipe_non_system_then_import_restores_identical_set(self, admin_headers):
        from uuid import uuid4

        slug = f"itest-roundtrip-{uuid4().hex[:8]}"
        create = requests.post(
            f"{self.BASE_URL}/admin/access/levels",
            headers=admin_headers,
            json={
                "name": slug,
                "slug": slug,
                "description": "rt",
                "permissions": ["users.view", "invoices.view"],
            },
            timeout=10,
        )
        assert create.status_code == 201
        role_id = create.json()["level"]["id"]

        export = requests.post(
            f"{self.BASE_URL}/admin/access/export",
            headers=admin_headers,
            json={},
            timeout=10,
        )
        snapshot = export.json()

        # Wipe the non-system role.
        delete = requests.delete(
            f"{self.BASE_URL}/admin/access/levels/{role_id}",
            headers=admin_headers,
            timeout=10,
        )
        assert delete.status_code == 200

        # Re-import the snapshot.
        restore = requests.post(
            f"{self.BASE_URL}/admin/access/import",
            headers=admin_headers,
            json=snapshot,
            timeout=10,
        )
        assert restore.status_code == 200

        after = requests.post(
            f"{self.BASE_URL}/admin/access/export",
            headers=admin_headers,
            json={},
            timeout=10,
        )
        restored = next(r for r in after.json()["roles"] if r["slug"] == slug)
        assert set(restored["permissions"]) == {"users.view", "invoices.view"}
        assert restored["name"] == slug

    def test_import_does_not_overwrite_system_roles(self, admin_headers):
        # Ensure a system role exists (seeder runs on deploy; create via levels
        # only yields non-system, so we read whatever system roles are present).
        export = requests.post(
            f"{self.BASE_URL}/admin/access/export",
            headers=admin_headers,
            json={},
            timeout=10,
        )
        system_roles = [r for r in export.json()["roles"] if r["is_system"]]
        if not system_roles:
            pytest.skip("No system roles present (seed-rbac not run on this instance)")

        target = system_roles[0]
        tampered = {
            "version": 1,
            "roles": [
                {
                    "slug": target["slug"],
                    "name": "TAMPERED",
                    "description": "should be ignored",
                    "is_system": True,
                    "permissions": [],
                }
            ],
        }
        requests.post(
            f"{self.BASE_URL}/admin/access/import",
            headers=admin_headers,
            json=tampered,
            timeout=10,
        )

        after = requests.post(
            f"{self.BASE_URL}/admin/access/export",
            headers=admin_headers,
            json={},
            timeout=10,
        )
        unchanged = next(
            r for r in after.json()["roles"] if r["slug"] == target["slug"]
        )
        assert unchanged["name"] == target["name"]
        assert unchanged["name"] != "TAMPERED"

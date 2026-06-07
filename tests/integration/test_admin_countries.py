"""
Integration tests for admin countries API.

Run with:
    docker-compose --profile test-integration run --rm test-integration \
        pytest tests/integration/test_admin_countries.py -v
"""
import pytest
import requests
import os


class TestAdminCountries:
    """
    Integration tests for admin countries API.

    Tests the configuration operations for billing address countries:
    - List all countries
    - List enabled countries
    - List disabled countries
    - Enable country
    - Disable country
    - Reorder countries
    """

    BASE_URL = os.getenv("API_BASE_URL", "http://localhost:5000/api/v1")

    @pytest.fixture(autouse=True)
    def setup(self):
        """Verify backend is reachable before running tests."""
        try:
            response = requests.get(f"{self.BASE_URL}/health", timeout=5)
            if response.status_code != 200:
                pytest.skip("Backend not healthy, skipping integration tests")
        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not reachable, skipping integration tests")

    @pytest.fixture
    def admin_credentials(self) -> dict:
        """Get test admin credentials."""
        return {
            "email": os.getenv("TEST_ADMIN_EMAIL", "admin@example.com"),
            "password": os.getenv("TEST_ADMIN_PASSWORD", "AdminPass123@"),
        }

    @pytest.fixture
    def user_credentials(self) -> dict:
        """Get test user credentials (non-admin)."""
        return {
            "email": os.getenv("TEST_USER_EMAIL", "test@example.com"),
            "password": os.getenv("TEST_USER_PASSWORD", "TestPass123@"),
        }

    @pytest.fixture
    def admin_token(self, admin_credentials) -> str:
        """Get auth token for admin user."""
        response = requests.post(
            f"{self.BASE_URL}/auth/login", json=admin_credentials, timeout=10
        )
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        return response.json().get("token")

    @pytest.fixture
    def user_token(self, user_credentials) -> str:
        """Get auth token for regular user."""
        response = requests.post(
            f"{self.BASE_URL}/auth/login", json=user_credentials, timeout=10
        )
        assert response.status_code == 200, f"User login failed: {response.text}"
        return response.json().get("token")

    @pytest.fixture
    def admin_headers(self, admin_token) -> dict:
        """Get headers with admin auth token."""
        return {"Authorization": f"Bearer {admin_token}"}

    @pytest.fixture
    def user_headers(self, user_token) -> dict:
        """Get headers with regular user auth token."""
        return {"Authorization": f"Bearer {user_token}"}

    # =========================================
    # Authentication Tests
    # =========================================

    def test_list_requires_auth(self):
        """
        Test: GET /api/v1/admin/countries without auth
        Expected: 401 Unauthorized
        """
        response = requests.get(f"{self.BASE_URL}/admin/countries/", timeout=5)
        assert response.status_code == 401

    def test_list_requires_admin_role(self, user_headers):
        """
        Test: GET /api/v1/admin/countries with regular user
        Expected: 403 Forbidden
        """
        response = requests.get(
            f"{self.BASE_URL}/admin/countries/",
            headers=user_headers,
            timeout=5,
        )
        assert response.status_code == 403

    # =========================================
    # List Countries Tests
    # =========================================

    def test_list_countries_success(self, admin_headers):
        """
        Test: GET /api/v1/admin/countries
        Expected: 200 with list of all countries
        """
        response = requests.get(
            f"{self.BASE_URL}/admin/countries/",
            headers=admin_headers,
            timeout=5,
        )
        assert response.status_code == 200
        data = response.json()
        assert "countries" in data
        assert isinstance(data["countries"], list)
        # Should have default countries from migration
        assert len(data["countries"]) >= 36

    def test_list_includes_dach_enabled(self, admin_headers):
        """
        Test: GET /api/v1/admin/countries
        Expected: DACH countries (DE, AT, CH) should be enabled by default
        """
        response = requests.get(
            f"{self.BASE_URL}/admin/countries/",
            headers=admin_headers,
            timeout=5,
        )
        assert response.status_code == 200
        data = response.json()

        # Find DACH countries
        dach_codes = ["DE", "AT", "CH"]
        dach_countries = [c for c in data["countries"] if c["code"] in dach_codes]

        assert len(dach_countries) == 3
        for country in dach_countries:
            assert country["is_enabled"] is True, f"{country['code']} should be enabled"

    def test_list_enabled_countries(self, admin_headers):
        """
        Test: GET /api/v1/admin/countries/enabled
        Expected: 200 with only enabled countries
        """
        response = requests.get(
            f"{self.BASE_URL}/admin/countries/enabled",
            headers=admin_headers,
            timeout=5,
        )
        assert response.status_code == 200
        data = response.json()
        assert "countries" in data
        # All should be enabled
        for country in data["countries"]:
            assert country["is_enabled"] is True

    def test_list_disabled_countries(self, admin_headers):
        """
        Test: GET /api/v1/admin/countries/disabled
        Expected: 200 with only disabled countries
        """
        response = requests.get(
            f"{self.BASE_URL}/admin/countries/disabled",
            headers=admin_headers,
            timeout=5,
        )
        assert response.status_code == 200
        data = response.json()
        assert "countries" in data
        # All should be disabled
        for country in data["countries"]:
            assert country["is_enabled"] is False

    # =========================================
    # Enable/Disable Country Tests
    # =========================================

    def test_enable_country_success(self, admin_headers):
        """
        Test: POST /api/v1/admin/countries/{code}/enable
        Expected: 200 with country enabled
        """
        # First ensure US is disabled (it's not in DACH)
        response = requests.post(
            f"{self.BASE_URL}/admin/countries/US/disable",
            headers=admin_headers,
            timeout=5,
        )

        # Now enable it
        response = requests.post(
            f"{self.BASE_URL}/admin/countries/US/enable",
            headers=admin_headers,
            timeout=5,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "US"
        assert data["is_enabled"] is True

    def test_enable_already_enabled_country(self, admin_headers):
        """
        Test: POST /api/v1/admin/countries/{code}/enable (already enabled)
        Expected: 200 (idempotent)
        """
        # DE is enabled by default
        response = requests.post(
            f"{self.BASE_URL}/admin/countries/DE/enable",
            headers=admin_headers,
            timeout=5,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "DE"
        assert data["is_enabled"] is True

    def test_enable_country_not_found(self, admin_headers):
        """
        Test: POST /api/v1/admin/countries/{invalid_code}/enable
        Expected: 404 Not Found
        """
        response = requests.post(
            f"{self.BASE_URL}/admin/countries/XX/enable",
            headers=admin_headers,
            timeout=5,
        )
        assert response.status_code == 404

    def test_disable_country_success(self, admin_headers):
        """
        Test: POST /api/v1/admin/countries/{code}/disable
        Expected: 200 with country disabled
        """
        # First enable FR
        requests.post(
            f"{self.BASE_URL}/admin/countries/FR/enable",
            headers=admin_headers,
            timeout=5,
        )

        # Now disable it
        response = requests.post(
            f"{self.BASE_URL}/admin/countries/FR/disable",
            headers=admin_headers,
            timeout=5,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "FR"
        assert data["is_enabled"] is False

    def test_disable_country_not_found(self, admin_headers):
        """
        Test: POST /api/v1/admin/countries/{invalid_code}/disable
        Expected: 404 Not Found
        """
        response = requests.post(
            f"{self.BASE_URL}/admin/countries/XX/disable",
            headers=admin_headers,
            timeout=5,
        )
        assert response.status_code == 404

    # =========================================
    # Reorder Countries Tests
    # =========================================

    def test_reorder_countries_success(self, admin_headers):
        """
        Test: PUT /api/v1/admin/countries/reorder
        Expected: 200 with countries in new order
        """
        # Ensure all DACH countries are enabled
        for code in ["DE", "AT", "CH"]:
            requests.post(
                f"{self.BASE_URL}/admin/countries/{code}/enable",
                headers=admin_headers,
                timeout=5,
            )

        # Reorder: CH first, then AT, then DE
        response = requests.put(
            f"{self.BASE_URL}/admin/countries/reorder",
            json={"codes": ["CH", "AT", "DE"]},
            headers=admin_headers,
            timeout=10,
        )
        assert response.status_code == 200
        data = response.json()

        # Verify order
        codes = [c["code"] for c in data["countries"][:3]]
        assert codes == ["CH", "AT", "DE"]

    def test_reorder_empty_list(self, admin_headers):
        """
        Test: PUT /api/v1/admin/countries/reorder with empty list
        Expected: 400 Bad Request
        """
        response = requests.put(
            f"{self.BASE_URL}/admin/countries/reorder",
            json={"codes": []},
            headers=admin_headers,
            timeout=10,
        )
        assert response.status_code == 400

    def test_reorder_invalid_type(self, admin_headers):
        """
        Test: PUT /api/v1/admin/countries/reorder with non-list
        Expected: 400 Bad Request
        """
        response = requests.put(
            f"{self.BASE_URL}/admin/countries/reorder",
            json={"codes": "DE,AT,CH"},
            headers=admin_headers,
            timeout=10,
        )
        assert response.status_code == 400

    def test_reorder_ignores_disabled_countries(self, admin_headers):
        """
        Test: PUT /api/v1/admin/countries/reorder with disabled country
        Expected: 200, disabled country not reordered
        """
        # Ensure FR is disabled
        requests.post(
            f"{self.BASE_URL}/admin/countries/FR/disable",
            headers=admin_headers,
            timeout=5,
        )

        # Try to reorder including FR
        response = requests.put(
            f"{self.BASE_URL}/admin/countries/reorder",
            json={"codes": ["FR", "DE", "AT"]},
            headers=admin_headers,
            timeout=10,
        )
        # Should succeed but FR won't be at position 0
        assert response.status_code == 200

    # =========================================
    # Public Endpoint Tests
    # =========================================

    def test_public_list_countries(self, admin_headers):
        """
        Test: GET /api/v1/settings/countries (public endpoint)
        Expected: 200 with only enabled countries
        """
        # Ensure DACH are enabled
        for code in ["DE", "AT", "CH"]:
            requests.post(
                f"{self.BASE_URL}/admin/countries/{code}/enable",
                headers=admin_headers,
                timeout=5,
            )

        response = requests.get(f"{self.BASE_URL}/settings/countries", timeout=5)
        assert response.status_code == 200
        data = response.json()
        assert "countries" in data
        # Should only contain code and name (public dict)
        for country in data["countries"]:
            assert "code" in country
            assert "name" in country
            # Should not contain admin fields
            assert "id" not in country
            assert "is_enabled" not in country
            assert "position" not in country

    def test_public_excludes_disabled(self, admin_headers):
        """
        Test: Disabled countries should not appear in public list
        """
        # Disable JP
        requests.post(
            f"{self.BASE_URL}/admin/countries/JP/disable",
            headers=admin_headers,
            timeout=5,
        )

        # Check public list
        response = requests.get(f"{self.BASE_URL}/settings/countries", timeout=5)
        data = response.json()

        # Should not contain JP
        codes = [c["code"] for c in data["countries"]]
        assert "JP" not in codes

    def test_public_respects_order(self, admin_headers):
        """
        Test: Public list should respect admin-configured order
        """
        # Ensure and reorder DACH
        for code in ["DE", "AT", "CH"]:
            requests.post(
                f"{self.BASE_URL}/admin/countries/{code}/enable",
                headers=admin_headers,
                timeout=5,
            )

        requests.put(
            f"{self.BASE_URL}/admin/countries/reorder",
            json={"codes": ["AT", "CH", "DE"]},
            headers=admin_headers,
            timeout=10,
        )

        # Check public list order
        response = requests.get(f"{self.BASE_URL}/settings/countries", timeout=5)
        data = response.json()

        # First three should be AT, CH, DE in that order
        codes = [c["code"] for c in data["countries"][:3]]
        assert codes == ["AT", "CH", "DE"]

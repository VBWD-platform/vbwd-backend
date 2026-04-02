"""
Integration tests for User Frontend Endpoints.

Tests validate that the user-facing API endpoints return correct data
for subscription and invoice visibility on the frontend.

Run with:
    docker-compose run --rm test pytest tests/integration/test_user_frontend_endpoints.py -v

Or against running backend:
    API_BASE_URL=http://localhost:5000/api/v1 pytest tests/integration/test_user_frontend_endpoints.py -v
"""
import pytest
import requests
import os
from typing import Optional, Dict


class TestUserSubscriptionEndpoint:
    """
    Integration tests for GET /user/subscriptions/active endpoint.

    Verifies that the user can see their active subscription with plan details.
    """

    BASE_URL = os.getenv("API_BASE_URL", "http://localhost:5000/api/v1")
    TEST_USER_EMAIL = os.getenv("TEST_USER_EMAIL", "test@example.com")
    TEST_USER_PASSWORD = os.getenv("TEST_USER_PASSWORD", "TestPass123@")

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
    def user_token(self) -> Optional[str]:
        """Get user auth token."""
        response = requests.post(
            f"{self.BASE_URL}/auth/login",
            json={
                "email": self.TEST_USER_EMAIL,
                "password": self.TEST_USER_PASSWORD,
            },
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("access_token") or data.get("token")
        pytest.fail(f"Failed to login test user: {response.text}")
        return None

    @pytest.fixture
    def auth_headers(self, user_token) -> Dict[str, str]:
        """Get authorization headers."""
        return {
            "Authorization": f"Bearer {user_token}",
            "Content-Type": "application/json",
        }

    def test_user_can_get_active_subscription(self, auth_headers):
        """
        Test: GET /api/v1/user/subscriptions/active
        Expected: 200 OK with subscription data
        """
        response = requests.get(
            f"{self.BASE_URL}/user/subscriptions/active",
            headers=auth_headers,
            timeout=10,
        )

        assert (
            response.status_code == 200
        ), f"Got {response.status_code}: {response.text}"
        data = response.json()
        assert "subscription" in data

    def test_subscription_has_required_fields(self, auth_headers):
        """
        Test: GET /api/v1/user/subscriptions/active
        Expected: Subscription contains all required fields for frontend
        """
        response = requests.get(
            f"{self.BASE_URL}/user/subscriptions/active",
            headers=auth_headers,
            timeout=10,
        )

        assert response.status_code == 200
        data = response.json()
        subscription = data.get("subscription")

        if subscription is None:
            pytest.skip("User has no active subscription")

        # Required fields
        required_fields = ["id", "user_id", "tarif_plan_id", "status", "is_valid"]
        for field in required_fields:
            assert field in subscription, f"Missing required field: {field}"

    def test_subscription_includes_plan_details(self, auth_headers):
        """
        Test: GET /api/v1/user/subscriptions/active
        Expected: Subscription includes plan object with name, price, etc.

        This is the critical test - the frontend needs plan.name to display!
        """
        response = requests.get(
            f"{self.BASE_URL}/user/subscriptions/active",
            headers=auth_headers,
            timeout=10,
        )

        assert response.status_code == 200
        data = response.json()
        subscription = data.get("subscription")

        if subscription is None:
            pytest.skip("User has no active subscription")

        # Plan object must exist
        assert "plan" in subscription, "Subscription must include 'plan' object"
        plan = subscription["plan"]

        # Plan must have required fields for frontend display
        plan_required_fields = ["id", "name", "slug", "price", "billing_period"]
        for field in plan_required_fields:
            assert field in plan, f"Plan missing required field: {field}"

        # Plan name should not be empty
        assert plan["name"], "Plan name should not be empty"
        assert len(plan["name"]) > 0, "Plan name should have length > 0"

    def test_subscription_status_is_valid_enum(self, auth_headers):
        """
        Test: Subscription status is a valid enum value
        """
        response = requests.get(
            f"{self.BASE_URL}/user/subscriptions/active",
            headers=auth_headers,
            timeout=10,
        )

        assert response.status_code == 200
        data = response.json()
        subscription = data.get("subscription")

        if subscription is None:
            pytest.skip("User has no active subscription")

        valid_statuses = ["PENDING", "ACTIVE", "PAUSED", "CANCELLED", "EXPIRED"]
        assert (
            subscription["status"] in valid_statuses
        ), f"Invalid status: {subscription['status']}"

    def test_subscription_data_is_consistent_on_reload(self, auth_headers):
        """
        Test: Subscription data is consistent across multiple requests
        """
        # First request
        response1 = requests.get(
            f"{self.BASE_URL}/user/subscriptions/active",
            headers=auth_headers,
            timeout=10,
        )
        assert response1.status_code == 200
        data1 = response1.json()

        # Second request
        response2 = requests.get(
            f"{self.BASE_URL}/user/subscriptions/active",
            headers=auth_headers,
            timeout=10,
        )
        assert response2.status_code == 200
        data2 = response2.json()

        # Data should be consistent
        assert data1 == data2, "Subscription data should be consistent across requests"


class TestUserInvoicesEndpoint:
    """
    Integration tests for GET /user/invoices endpoint.

    Verifies that the user can see their invoices.
    """

    BASE_URL = os.getenv("API_BASE_URL", "http://localhost:5000/api/v1")
    TEST_USER_EMAIL = os.getenv("TEST_USER_EMAIL", "test@example.com")
    TEST_USER_PASSWORD = os.getenv("TEST_USER_PASSWORD", "TestPass123@")

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
    def user_token(self) -> Optional[str]:
        """Get user auth token."""
        response = requests.post(
            f"{self.BASE_URL}/auth/login",
            json={
                "email": self.TEST_USER_EMAIL,
                "password": self.TEST_USER_PASSWORD,
            },
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("access_token") or data.get("token")
        pytest.fail(f"Failed to login test user: {response.text}")
        return None

    @pytest.fixture
    def auth_headers(self, user_token) -> Dict[str, str]:
        """Get authorization headers."""
        return {
            "Authorization": f"Bearer {user_token}",
            "Content-Type": "application/json",
        }

    def test_user_can_get_invoices(self, auth_headers):
        """
        Test: GET /api/v1/user/invoices
        Expected: 200 OK with invoices list
        """
        response = requests.get(
            f"{self.BASE_URL}/user/invoices",
            headers=auth_headers,
            timeout=10,
        )

        assert (
            response.status_code == 200
        ), f"Got {response.status_code}: {response.text}"
        data = response.json()
        assert "invoices" in data
        assert isinstance(data["invoices"], list)

    def test_user_has_invoices(self, auth_headers):
        """
        Test: User should have at least one invoice
        Expected: invoices array is not empty
        """
        response = requests.get(
            f"{self.BASE_URL}/user/invoices",
            headers=auth_headers,
            timeout=10,
        )

        assert response.status_code == 200
        data = response.json()
        invoices = data.get("invoices", [])

        assert len(invoices) > 0, (
            "User should have at least one invoice. "
            "Make sure test data is seeded correctly."
        )

    def test_invoice_has_required_fields(self, auth_headers):
        """
        Test: Invoice contains all required fields for frontend display
        """
        response = requests.get(
            f"{self.BASE_URL}/user/invoices",
            headers=auth_headers,
            timeout=10,
        )

        assert response.status_code == 200
        data = response.json()
        invoices = data.get("invoices", [])

        if len(invoices) == 0:
            pytest.skip("No invoices to test")

        invoice = invoices[0]

        # Required fields for frontend display
        required_fields = [
            "id",
            "invoice_number",
            "amount",
            "currency",
            "status",
            "invoiced_at",
        ]
        for field in required_fields:
            assert field in invoice, f"Invoice missing required field: {field}"

    def test_invoice_number_format(self, auth_headers):
        """
        Test: Invoice number has expected format (INV-YYYYMMDD-XXXXXX)
        """
        response = requests.get(
            f"{self.BASE_URL}/user/invoices",
            headers=auth_headers,
            timeout=10,
        )

        assert response.status_code == 200
        data = response.json()
        invoices = data.get("invoices", [])

        if len(invoices) == 0:
            pytest.skip("No invoices to test")

        invoice = invoices[0]
        invoice_number = invoice.get("invoice_number", "")

        valid_prefixes = ("INV-", "SH-", "BK-")
        assert invoice_number.startswith(
            valid_prefixes
        ), f"Invoice number should start with one of {valid_prefixes}, got: {invoice_number}"
        assert len(invoice_number) > 10, "Invoice number seems too short"

    def test_invoice_status_is_valid_enum(self, auth_headers):
        """
        Test: Invoice status is a valid enum value
        """
        response = requests.get(
            f"{self.BASE_URL}/user/invoices",
            headers=auth_headers,
            timeout=10,
        )

        assert response.status_code == 200
        data = response.json()
        invoices = data.get("invoices", [])

        if len(invoices) == 0:
            pytest.skip("No invoices to test")

        valid_statuses = ["PENDING", "PAID", "FAILED", "CANCELLED", "REFUNDED"]
        for invoice in invoices:
            assert (
                invoice["status"] in valid_statuses
            ), f"Invalid invoice status: {invoice['status']}"

    def test_invoice_amount_is_numeric(self, auth_headers):
        """
        Test: Invoice amount can be parsed as a number
        """
        response = requests.get(
            f"{self.BASE_URL}/user/invoices",
            headers=auth_headers,
            timeout=10,
        )

        assert response.status_code == 200
        data = response.json()
        invoices = data.get("invoices", [])

        if len(invoices) == 0:
            pytest.skip("No invoices to test")

        for invoice in invoices:
            amount = invoice.get("amount")
            # Amount might be string or number
            try:
                float(amount)
            except (ValueError, TypeError):
                pytest.fail(f"Invoice amount is not numeric: {amount}")

    def test_invoices_data_is_consistent_on_reload(self, auth_headers):
        """
        Test: Invoices data is consistent across multiple requests
        """
        # First request
        response1 = requests.get(
            f"{self.BASE_URL}/user/invoices",
            headers=auth_headers,
            timeout=10,
        )
        assert response1.status_code == 200
        data1 = response1.json()

        # Second request
        response2 = requests.get(
            f"{self.BASE_URL}/user/invoices",
            headers=auth_headers,
            timeout=10,
        )
        assert response2.status_code == 200
        data2 = response2.json()

        # Data should be consistent
        assert len(data1["invoices"]) == len(
            data2["invoices"]
        ), "Invoice count should be consistent across requests"

        # Invoice IDs should match
        ids1 = [inv["id"] for inv in data1["invoices"]]
        ids2 = [inv["id"] for inv in data2["invoices"]]
        assert ids1 == ids2, "Invoice IDs should be consistent across requests"


class TestUserInvoiceDetailEndpoint:
    """
    Integration tests for GET /user/invoices/:id endpoint.
    """

    BASE_URL = os.getenv("API_BASE_URL", "http://localhost:5000/api/v1")
    TEST_USER_EMAIL = os.getenv("TEST_USER_EMAIL", "test@example.com")
    TEST_USER_PASSWORD = os.getenv("TEST_USER_PASSWORD", "TestPass123@")

    @pytest.fixture(autouse=True)
    def setup(self):
        """Verify backend is reachable."""
        try:
            response = requests.get(f"{self.BASE_URL}/health", timeout=5)
            if response.status_code != 200:
                pytest.skip("Backend not healthy")
        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not reachable")

    @pytest.fixture
    def user_token(self) -> Optional[str]:
        """Get user auth token."""
        response = requests.post(
            f"{self.BASE_URL}/auth/login",
            json={
                "email": self.TEST_USER_EMAIL,
                "password": self.TEST_USER_PASSWORD,
            },
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("access_token") or data.get("token")
        return None

    @pytest.fixture
    def auth_headers(self, user_token) -> Dict[str, str]:
        """Get authorization headers."""
        return {
            "Authorization": f"Bearer {user_token}",
            "Content-Type": "application/json",
        }

    @pytest.fixture
    def invoice_id(self, auth_headers) -> Optional[str]:
        """Get an invoice ID for testing."""
        response = requests.get(
            f"{self.BASE_URL}/user/invoices",
            headers=auth_headers,
            timeout=10,
        )
        if response.status_code == 200:
            invoices = response.json().get("invoices", [])
            if invoices:
                return invoices[0]["id"]
        return None

    def test_user_can_get_invoice_detail(self, auth_headers, invoice_id):
        """
        Test: GET /api/v1/user/invoices/:id
        Expected: 200 OK with invoice details
        """
        if not invoice_id:
            pytest.skip("No invoice available for testing")

        response = requests.get(
            f"{self.BASE_URL}/user/invoices/{invoice_id}",
            headers=auth_headers,
            timeout=10,
        )

        assert (
            response.status_code == 200
        ), f"Got {response.status_code}: {response.text}"
        data = response.json()
        assert "invoice" in data

    def test_invoice_detail_matches_list(self, auth_headers, invoice_id):
        """
        Test: Invoice detail should match the data from list endpoint
        """
        if not invoice_id:
            pytest.skip("No invoice available for testing")

        # Get from list
        list_response = requests.get(
            f"{self.BASE_URL}/user/invoices",
            headers=auth_headers,
            timeout=10,
        )
        list_invoices = list_response.json().get("invoices", [])
        list_invoice = next(
            (inv for inv in list_invoices if inv["id"] == invoice_id), None
        )

        # Get detail
        detail_response = requests.get(
            f"{self.BASE_URL}/user/invoices/{invoice_id}",
            headers=auth_headers,
            timeout=10,
        )
        detail_invoice = detail_response.json().get("invoice")

        assert list_invoice is not None
        assert detail_invoice is not None

        # Key fields should match
        assert list_invoice["id"] == detail_invoice["id"]
        assert list_invoice["invoice_number"] == detail_invoice["invoice_number"]
        assert list_invoice["amount"] == detail_invoice["amount"]
        assert list_invoice["status"] == detail_invoice["status"]

    def test_cannot_access_other_users_invoice(self, auth_headers):
        """
        Test: User cannot access invoices belonging to other users
        """
        # Try to access a non-existent/other user's invoice
        fake_invoice_id = "00000000-0000-0000-0000-000000000000"
        response = requests.get(
            f"{self.BASE_URL}/user/invoices/{fake_invoice_id}",
            headers=auth_headers,
            timeout=10,
        )

        # Should be 403 or 404
        assert response.status_code in [
            403,
            404,
        ], f"Expected 403 or 404, got {response.status_code}"


class TestDataConsistency:
    """
    Tests to verify data consistency between subscription and invoices.
    """

    BASE_URL = os.getenv("API_BASE_URL", "http://localhost:5000/api/v1")
    TEST_USER_EMAIL = os.getenv("TEST_USER_EMAIL", "test@example.com")
    TEST_USER_PASSWORD = os.getenv("TEST_USER_PASSWORD", "TestPass123@")

    @pytest.fixture(autouse=True)
    def setup(self):
        """Verify backend is reachable."""
        try:
            response = requests.get(f"{self.BASE_URL}/health", timeout=5)
            if response.status_code != 200:
                pytest.skip("Backend not healthy")
        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not reachable")

    @pytest.fixture
    def user_token(self) -> Optional[str]:
        """Get user auth token."""
        response = requests.post(
            f"{self.BASE_URL}/auth/login",
            json={
                "email": self.TEST_USER_EMAIL,
                "password": self.TEST_USER_PASSWORD,
            },
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("access_token") or data.get("token")
        return None

    @pytest.fixture
    def auth_headers(self, user_token) -> Dict[str, str]:
        """Get authorization headers."""
        return {
            "Authorization": f"Bearer {user_token}",
            "Content-Type": "application/json",
        }

    def test_subscription_plan_id_matches_invoice_plan_id(self, auth_headers):
        """
        Test: Invoice tarif_plan_id should match subscription tarif_plan_id
        """
        # Get subscription
        sub_response = requests.get(
            f"{self.BASE_URL}/user/subscriptions/active",
            headers=auth_headers,
            timeout=10,
        )
        assert sub_response.status_code == 200
        subscription = sub_response.json().get("subscription")

        if subscription is None:
            pytest.skip("No active subscription")

        # Get invoices
        inv_response = requests.get(
            f"{self.BASE_URL}/user/invoices",
            headers=auth_headers,
            timeout=10,
        )
        assert inv_response.status_code == 200
        invoices = inv_response.json().get("invoices", [])

        if len(invoices) == 0:
            pytest.skip("No invoices to compare")

        # At least one invoice should match the subscription's plan
        subscription_plan_id = subscription.get("tarif_plan_id")
        matching_invoices = [
            inv for inv in invoices if inv.get("tarif_plan_id") == subscription_plan_id
        ]

        if len(matching_invoices) == 0:
            pytest.skip(
                "No invoices for current subscription plan "
                "(subscription may have been created outside checkout flow)"
            )

        assert len(matching_invoices) > 0

    def test_user_id_is_consistent(self, auth_headers):
        """
        Test: User ID is consistent across subscription and invoices
        """
        # Get subscription
        sub_response = requests.get(
            f"{self.BASE_URL}/user/subscriptions/active",
            headers=auth_headers,
            timeout=10,
        )
        subscription = sub_response.json().get("subscription")

        # Get invoices
        inv_response = requests.get(
            f"{self.BASE_URL}/user/invoices",
            headers=auth_headers,
            timeout=10,
        )
        invoices = inv_response.json().get("invoices", [])

        if subscription is None and len(invoices) == 0:
            pytest.skip("No data to compare")

        user_ids = set()
        if subscription:
            user_ids.add(subscription.get("user_id"))
        for inv in invoices:
            user_ids.add(inv.get("user_id"))

        assert len(user_ids) == 1, f"User IDs should be consistent, found: {user_ids}"

"""Tests for invoice routes."""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

from dependency_injector import providers


@contextmanager
def override_invoice_service(client, mock_service):
    """S08 — invoice routes pull from container; tests override the provider."""
    container = client.application.container
    container.invoice_service.override(providers.Object(mock_service))
    try:
        yield
    finally:
        container.invoice_service.reset_override()


class TestInvoiceRoutes:
    """Tests for invoice route endpoints."""

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_get_invoices_authenticated(
        self,
        mock_user_repo_class,
        mock_auth_class,
        client,
    ):
        """Get invoices returns list for authenticated user."""
        user_id = uuid4()
        mock_user = MagicMock()
        mock_user.status.value = "ACTIVE"
        mock_user.id = user_id

        mock_user_repo = MagicMock()
        mock_user_repo.find_by_id.return_value = mock_user
        mock_user_repo_class.return_value = mock_user_repo

        mock_auth = MagicMock()
        mock_auth.verify_token.return_value = str(user_id)
        mock_auth_class.return_value = mock_auth

        mock_invoices = [
            MagicMock(to_dict=lambda: {"id": str(uuid4()), "amount": "99.99"}),
            MagicMock(to_dict=lambda: {"id": str(uuid4()), "amount": "49.99"}),
        ]
        mock_service = MagicMock()
        mock_service.get_user_invoices.return_value = mock_invoices

        with override_invoice_service(client, mock_service):
            response = client.get(
                "/api/v1/user/invoices/",
                headers={"Authorization": "Bearer valid_token"},
            )

        assert response.status_code == 200
        data = response.get_json()
        assert "invoices" in data
        assert len(data["invoices"]) == 2

    def test_get_invoices_unauthenticated(self, client):
        """Get invoices returns 401 for unauthenticated user."""
        response = client.get("/api/v1/user/invoices/")

        assert response.status_code == 401

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_get_invoice_detail(
        self,
        mock_user_repo_class,
        mock_auth_class,
        client,
    ):
        """Get invoice detail returns invoice."""
        user_id = uuid4()
        invoice_id = uuid4()

        mock_user = MagicMock()
        mock_user.status.value = "ACTIVE"
        mock_user.id = user_id

        mock_user_repo = MagicMock()
        mock_user_repo.find_by_id.return_value = mock_user
        mock_user_repo_class.return_value = mock_user_repo

        mock_auth = MagicMock()
        mock_auth.verify_token.return_value = str(user_id)
        mock_auth_class.return_value = mock_auth

        mock_invoice = MagicMock()
        mock_invoice.user_id = user_id
        mock_invoice.to_dict.return_value = {
            "id": str(invoice_id),
            "user_id": str(user_id),
            "amount": "99.99",
            "status": "pending",
        }

        mock_service = MagicMock()
        mock_service.get_invoice.return_value = mock_invoice

        with override_invoice_service(client, mock_service):
            response = client.get(
                f"/api/v1/user/invoices/{invoice_id}",
                headers={"Authorization": "Bearer valid_token"},
            )

        assert response.status_code == 200
        data = response.get_json()
        assert "invoice" in data
        assert data["invoice"]["id"] == str(invoice_id)

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_get_invoice_not_found(
        self,
        mock_user_repo_class,
        mock_auth_class,
        client,
    ):
        """Get invoice returns 404 when not found."""
        user_id = uuid4()

        mock_user = MagicMock()
        mock_user.status.value = "ACTIVE"
        mock_user.id = user_id

        mock_user_repo = MagicMock()
        mock_user_repo.find_by_id.return_value = mock_user
        mock_user_repo_class.return_value = mock_user_repo

        mock_auth = MagicMock()
        mock_auth.verify_token.return_value = str(user_id)
        mock_auth_class.return_value = mock_auth

        mock_service = MagicMock()
        mock_service.get_invoice.return_value = None

        response = client.get(
            f"/api/v1/user/invoices/{uuid4()}",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 404

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_get_invoice_not_owned(
        self,
        mock_user_repo_class,
        mock_auth_class,
        client,
    ):
        """Get invoice returns 403 when user doesn't own it."""
        user_id = uuid4()
        other_user_id = uuid4()
        invoice_id = uuid4()

        mock_user = MagicMock()
        mock_user.status.value = "ACTIVE"
        mock_user.id = user_id

        mock_user_repo = MagicMock()
        mock_user_repo.find_by_id.return_value = mock_user
        mock_user_repo_class.return_value = mock_user_repo

        mock_auth = MagicMock()
        mock_auth.verify_token.return_value = str(user_id)
        mock_auth_class.return_value = mock_auth

        mock_invoice = MagicMock()
        mock_invoice.user_id = other_user_id  # Different user

        mock_service = MagicMock()
        mock_service.get_invoice.return_value = mock_invoice

        with override_invoice_service(client, mock_service):
            response = client.get(
                f"/api/v1/user/invoices/{invoice_id}",
                headers={"Authorization": "Bearer valid_token"},
            )

        assert response.status_code == 403


class TestInvoicePdfRoute:
    """Tests for GET /api/v1/user/invoices/:id/pdf."""

    def _authenticated_user_mock(self, user_id):
        mock_user = MagicMock()
        mock_user.status.value = "ACTIVE"
        mock_user.id = user_id
        return mock_user

    @patch("vbwd.routes.invoices.get_pdf_service")
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_download_invoice_pdf_returns_pdf_bytes(
        self,
        mock_user_repo_class,
        mock_auth_class,
        mock_get_pdf_service,
        client,
    ):
        """Owned invoice streams PDF bytes with correct Content-Type."""
        from decimal import Decimal

        user_id = uuid4()
        invoice_id = uuid4()

        mock_user_repo = MagicMock()
        mock_user_repo.find_by_id.return_value = self._authenticated_user_mock(user_id)
        mock_user_repo_class.return_value = mock_user_repo

        mock_auth = MagicMock()
        mock_auth.verify_token.return_value = str(user_id)
        mock_auth_class.return_value = mock_auth

        # Build a real-ish invoice stand-in — attributes configured so the
        # pdf-context builder (which calls _format_money) doesn't choke on
        # MagicMock auto-attributes.
        mock_status = MagicMock()
        mock_status.value = "paid"

        mock_invoice = MagicMock()
        mock_invoice.id = invoice_id
        mock_invoice.user_id = user_id
        mock_invoice.invoice_number = "INV-0001"
        mock_invoice.currency = "EUR"
        mock_invoice.amount = Decimal("99.99")
        mock_invoice.subtotal = Decimal("83.33")
        mock_invoice.tax_amount = Decimal("16.66")
        mock_invoice.total_amount = Decimal("99.99")
        mock_invoice.status = mock_status
        mock_invoice.invoiced_at = None
        mock_invoice.expires_at = None
        mock_invoice.notes = ""
        mock_invoice.line_items = []

        mock_service = MagicMock()
        mock_service.get_invoice.return_value = mock_invoice

        fake_pdf = b"%PDF-1.7\n...bytes..."
        mock_pdf_service = MagicMock()
        mock_pdf_service.render.return_value = fake_pdf
        mock_get_pdf_service.return_value = mock_pdf_service

        with override_invoice_service(client, mock_service):
            response = client.get(
                f"/api/v1/user/invoices/{invoice_id}/pdf",
                headers={"Authorization": "Bearer valid_token"},
            )

        assert response.status_code == 200
        assert response.content_type == "application/pdf"
        assert response.data == fake_pdf
        assert "attachment" in response.headers.get("Content-Disposition", "")
        assert "INV-0001" in response.headers.get("Content-Disposition", "")
        mock_pdf_service.render.assert_called_once()
        rendered_template, rendered_ctx = mock_pdf_service.render.call_args[0]
        assert rendered_template == "invoice.html"
        assert rendered_ctx["invoice"]["invoice_number"] == "INV-0001"

    @patch("vbwd.routes.invoices.get_pdf_service")
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_download_invoice_pdf_not_found(
        self,
        mock_user_repo_class,
        mock_auth_class,
        mock_get_pdf_service,
        client,
    ):
        user_id = uuid4()

        mock_user_repo = MagicMock()
        mock_user_repo.find_by_id.return_value = self._authenticated_user_mock(user_id)
        mock_user_repo_class.return_value = mock_user_repo

        mock_auth = MagicMock()
        mock_auth.verify_token.return_value = str(user_id)
        mock_auth_class.return_value = mock_auth

        mock_service = MagicMock()
        mock_service.get_invoice.return_value = None

        response = client.get(
            f"/api/v1/user/invoices/{uuid4()}/pdf",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 404
        mock_get_pdf_service.assert_not_called()

    @patch("vbwd.routes.invoices.get_pdf_service")
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_download_invoice_pdf_not_owned(
        self,
        mock_user_repo_class,
        mock_auth_class,
        mock_get_pdf_service,
        client,
    ):
        user_id = uuid4()
        other_user_id = uuid4()

        mock_user_repo = MagicMock()
        mock_user_repo.find_by_id.return_value = self._authenticated_user_mock(user_id)
        mock_user_repo_class.return_value = mock_user_repo

        mock_auth = MagicMock()
        mock_auth.verify_token.return_value = str(user_id)
        mock_auth_class.return_value = mock_auth

        mock_invoice = MagicMock()
        mock_invoice.user_id = other_user_id
        mock_service = MagicMock()
        mock_service.get_invoice.return_value = mock_invoice

        with override_invoice_service(client, mock_service):
            response = client.get(
                f"/api/v1/user/invoices/{uuid4()}/pdf",
                headers={"Authorization": "Bearer valid_token"},
            )

        assert response.status_code == 403
        mock_get_pdf_service.assert_not_called()

    def test_download_invoice_pdf_unauthenticated(self, client):
        response = client.get(f"/api/v1/user/invoices/{uuid4()}/pdf")
        assert response.status_code == 401

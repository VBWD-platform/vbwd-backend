"""Tests for YooKassa plugin API routes."""
import json
import pytest
from decimal import Decimal
from uuid import uuid4, UUID
from unittest.mock import MagicMock, patch

from flask import Flask

from src.plugins.config_store import PluginConfigEntry
from src.models.enums import InvoiceStatus


@pytest.fixture
def mock_container(mocker):
    """Mock DI container with repositories and event dispatcher."""
    container = mocker.MagicMock()
    container.invoice_repository.return_value = mocker.MagicMock()
    container.subscription_repository.return_value = mocker.MagicMock()
    container.user_repository.return_value = mocker.MagicMock()
    container.addon_subscription_repository.return_value = mocker.MagicMock()
    container.event_dispatcher.return_value = mocker.MagicMock()
    return container


@pytest.fixture
def app(mock_yookassa_api, mock_config_store, mock_container, mocker):
    """Create Flask app with YooKassa blueprint registered."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True

    user_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    mock_auth_service = MagicMock()
    mock_auth_service.return_value.verify_token.return_value = str(user_id)
    mocker.patch("src.middleware.auth.AuthService", mock_auth_service)

    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.status.value = "ACTIVE"

    mock_user_repo = MagicMock()
    mock_user_repo.return_value.find_by_id.return_value = mock_user
    mocker.patch("src.middleware.auth.UserRepository", mock_user_repo)

    mock_db = MagicMock()
    mocker.patch("src.middleware.auth.db", mock_db)

    from plugins.yookassa.routes import yookassa_plugin_bp

    flask_app.register_blueprint(
        yookassa_plugin_bp, url_prefix="/api/v1/plugins/yookassa"
    )

    flask_app.config_store = mock_config_store
    flask_app.container = mock_container

    return flask_app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def auth_headers():
    """Auth headers with a dummy bearer token."""
    return {"Authorization": "Bearer test_token_123"}


# ---- create-session tests ----


class TestCreateSession:
    """Tests for POST /api/v1/plugins/yookassa/create-session."""

    def test_create_session_requires_auth(self, client):
        """Should return 401 without Authorization header."""
        resp = client.post(
            "/api/v1/plugins/yookassa/create-session",
            json={"invoice_id": str(uuid4())},
        )
        assert resp.status_code == 401

    def test_create_session_plugin_disabled(
        self, client, app, mock_config_store_disabled, auth_headers
    ):
        """Should return 404 when plugin is disabled."""
        app.config_store = mock_config_store_disabled
        resp = client.post(
            "/api/v1/plugins/yookassa/create-session",
            json={"invoice_id": str(uuid4())},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_create_session_missing_invoice_id(
        self, client, auth_headers, mock_container
    ):
        """Should return 400 when invoice_id is missing."""
        mock_container.invoice_repository.return_value.find_by_id.return_value = None
        resp = client.post(
            "/api/v1/plugins/yookassa/create-session",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_create_session_invoice_not_found(
        self, client, auth_headers, mock_container
    ):
        """Should return 404 when invoice does not exist."""
        mock_container.invoice_repository.return_value.find_by_id.return_value = None
        resp = client.post(
            "/api/v1/plugins/yookassa/create-session",
            json={"invoice_id": str(uuid4())},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_create_session_invoice_not_pending(
        self, client, auth_headers, mock_container
    ):
        """Should return 400 when invoice status is not pending."""
        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.status = InvoiceStatus.PAID
        invoice.user_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        mock_container.invoice_repository.return_value.find_by_id.return_value = invoice

        resp = client.post(
            "/api/v1/plugins/yookassa/create-session",
            json={"invoice_id": str(invoice.id)},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_create_session_wrong_user(self, client, auth_headers, mock_container):
        """Should return 403 when invoice belongs to a different user."""
        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.status = InvoiceStatus.PENDING
        invoice.user_id = uuid4()
        mock_container.invoice_repository.return_value.find_by_id.return_value = invoice

        resp = client.post(
            "/api/v1/plugins/yookassa/create-session",
            json={"invoice_id": str(invoice.id)},
            headers=auth_headers,
        )
        assert resp.status_code == 403

    def test_create_session_success(
        self, client, auth_headers, mock_container, mock_yookassa_api
    ):
        """Should return 200 with session_id and session_url on success."""
        user_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.status = InvoiceStatus.PENDING
        invoice.user_id = user_id
        invoice.total_amount = Decimal("299.99")
        invoice.amount = Decimal("299.99")
        invoice.currency = "RUB"
        invoice.line_items = []
        mock_container.invoice_repository.return_value.find_by_id.return_value = invoice

        # Mock YooKassa payment creation
        payment_resp = MagicMock()
        payment_resp.status_code = 200
        payment_resp.json.return_value = {
            "id": "pay_yk_123",
            "status": "pending",
            "confirmation": {
                "type": "redirect",
                "confirmation_url": "https://yookassa.ru/checkout/pay/pay_yk_123",
            },
            "payment_method": {},
        }
        mock_yookassa_api.post.return_value = payment_resp

        resp = client.post(
            "/api/v1/plugins/yookassa/create-session",
            json={"invoice_id": str(invoice.id)},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["session_id"] == "pay_yk_123"
        assert "session_url" in data

    def test_create_session_stores_provider_session_id(
        self, client, auth_headers, mock_container, mock_yookassa_api
    ):
        """Should store YooKassa payment ID on the invoice."""
        user_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.status = InvoiceStatus.PENDING
        invoice.user_id = user_id
        invoice.total_amount = Decimal("100.00")
        invoice.amount = Decimal("100.00")
        invoice.currency = "RUB"
        invoice.line_items = []
        mock_container.invoice_repository.return_value.find_by_id.return_value = invoice

        payment_resp = MagicMock()
        payment_resp.status_code = 200
        payment_resp.json.return_value = {
            "id": "pay_stored",
            "status": "pending",
            "confirmation": {"confirmation_url": "https://yookassa.ru/pay"},
            "payment_method": {},
        }
        mock_yookassa_api.post.return_value = payment_resp

        client.post(
            "/api/v1/plugins/yookassa/create-session",
            json={"invoice_id": str(invoice.id)},
            headers=auth_headers,
        )

        assert invoice.provider_session_id == "pay_stored"
        mock_container.invoice_repository.return_value.save.assert_called_once()


# ---- webhook tests ----


class TestWebhook:
    """Tests for POST /api/v1/plugins/yookassa/webhook."""

    def _make_signed_webhook(self, client, event_payload, yookassa_config):
        """Helper to make a correctly signed webhook call."""
        import hashlib
        import hmac

        payload_bytes = json.dumps(event_payload).encode()
        secret = yookassa_config["test_webhook_secret"]
        sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

        return client.post(
            "/api/v1/plugins/yookassa/webhook",
            data=payload_bytes,
            headers={"X-YooKassa-Signature": sig},
            content_type="application/json",
        )

    def test_webhook_invalid_signature(self, client):
        """Should return 400 when signature verification fails."""
        resp = client.post(
            "/api/v1/plugins/yookassa/webhook",
            data=json.dumps({"event": "test"}).encode(),
            headers={"X-YooKassa-Signature": "bad_sig"},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_webhook_plugin_disabled(self, client, app, mock_config_store_disabled):
        """Should return 404 when plugin is disabled."""
        app.config_store = mock_config_store_disabled
        resp = client.post(
            "/api/v1/plugins/yookassa/webhook",
            data=b"raw_body",
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_webhook_payment_succeeded(self, client, mock_container, yookassa_config):
        """Should return 200 and emit event for payment.succeeded."""
        invoice_id = str(uuid4())
        event_payload = {
            "event": "payment.succeeded",
            "object": {
                "id": "pay_wh_1",
                "metadata": {"invoice_id": invoice_id},
                "amount": {"value": "299.99", "currency": "RUB"},
                "payment_method": {"id": "pm_1", "saved": False},
            },
        }

        mock_invoice = MagicMock()
        mock_invoice.id = UUID(invoice_id)
        mock_invoice.status.value = "PENDING"
        mock_invoice.line_items = []
        mock_container.invoice_repository.return_value.find_by_id.return_value = (
            mock_invoice
        )

        resp = self._make_signed_webhook(client, event_payload, yookassa_config)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["received"] is True
        mock_container.event_dispatcher.return_value.emit.assert_called_once()

    def test_webhook_ignores_unknown_events(
        self, client, mock_container, yookassa_config
    ):
        """Should return 200 but emit no event for unknown event types."""
        event_payload = {
            "event": "some.unknown.event",
            "object": {},
        }
        resp = self._make_signed_webhook(client, event_payload, yookassa_config)
        assert resp.status_code == 200
        mock_container.event_dispatcher.return_value.emit.assert_not_called()


# ---- session-status tests ----


class TestSessionStatus:
    """Tests for GET /api/v1/plugins/yookassa/session-status/<payment_id>."""

    def test_session_status_requires_auth(self, client):
        """Should return 401 without Authorization header."""
        resp = client.get("/api/v1/plugins/yookassa/session-status/pay_123")
        assert resp.status_code == 401

    def test_session_status_success(self, client, auth_headers, mock_yookassa_api):
        """Should return 200 with mapped status data."""
        status_resp = MagicMock()
        status_resp.status_code = 200
        status_resp.json.return_value = {
            "id": "pay_poll",
            "status": "succeeded",
            "amount": {"value": "299.99", "currency": "RUB"},
            "metadata": {"invoice_id": ""},
            "payment_method": {},
        }
        mock_yookassa_api.get.return_value = status_resp

        resp = client.get(
            "/api/v1/plugins/yookassa/session-status/pay_poll",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "paid"  # succeeded mapped to "paid"
        assert data["amount_total"] == "299.99"

    def test_session_status_pending(self, client, auth_headers, mock_yookassa_api):
        """Should return raw status for non-succeeded payments."""
        status_resp = MagicMock()
        status_resp.status_code = 200
        status_resp.json.return_value = {
            "id": "pay_pend",
            "status": "pending",
            "amount": {"value": "50.00", "currency": "RUB"},
            "metadata": {},
            "payment_method": {},
        }
        mock_yookassa_api.get.return_value = status_resp

        resp = client.get(
            "/api/v1/plugins/yookassa/session-status/pay_pend",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "pending"

    def test_session_status_error(self, client, auth_headers, mock_yookassa_api):
        """Should return 500 when YooKassa API fails."""
        error_resp = MagicMock()
        error_resp.status_code = 404
        error_resp.text = "Not found"
        error_resp.json.return_value = {}
        mock_yookassa_api.get.return_value = error_resp

        resp = client.get(
            "/api/v1/plugins/yookassa/session-status/nonexistent",
            headers=auth_headers,
        )
        assert resp.status_code == 500

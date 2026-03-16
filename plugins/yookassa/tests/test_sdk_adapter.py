"""Tests for YooKassaSDKAdapter."""
import json
import pytest
from decimal import Decimal
from unittest.mock import MagicMock

from src.sdk.interface import SDKConfig, SDKResponse
from src.sdk.base import BaseSDKAdapter


@pytest.fixture
def adapter(mock_yookassa_api):
    """Create YooKassaSDKAdapter with mocked requests module."""
    from plugins.yookassa.sdk_adapter import YooKassaSDKAdapter

    config = SDKConfig(
        api_key="test_shop_123", api_secret="test_secret_456", sandbox=True
    )
    return YooKassaSDKAdapter(config)


class TestYooKassaSDKAdapter:
    """Tests for YooKassaSDKAdapter."""

    def test_provider_name(self, adapter):
        """provider_name should return 'yookassa'."""
        assert adapter.provider_name == "yookassa"

    def test_inherits_base_sdk_adapter(self, adapter):
        """YooKassaSDKAdapter should inherit from BaseSDKAdapter."""
        assert isinstance(adapter, BaseSDKAdapter)

    def test_base_url(self, adapter):
        """Should use YooKassa API v3 URL."""
        assert adapter.BASE_URL == "https://api.yookassa.ru/v3"

    def test_auth_tuple(self, adapter):
        """Should return (shop_id, secret_key) for HTTP Basic Auth."""
        auth = adapter._auth()
        assert auth == ("test_shop_123", "test_secret_456")

    def test_create_payment_intent_success(self, adapter, mock_yookassa_api):
        """create_payment_intent should return session_id and session_url."""
        payment_resp = MagicMock()
        payment_resp.status_code = 200
        payment_resp.json.return_value = {
            "id": "2a5c5d6e-0000-1111-2222-333344445555",
            "status": "pending",
            "confirmation": {
                "type": "redirect",
                "confirmation_url": "https://yookassa.ru/checkout/pay/2a5c5d6e",
            },
            "payment_method": {},
        }
        mock_yookassa_api.post.return_value = payment_resp

        result = adapter.create_payment_intent(
            amount=Decimal("299.99"),
            currency="RUB",
            metadata={
                "invoice_id": "inv_123",
                "success_url": "https://example.com/ok",
                "cancel_url": "https://example.com/cancel",
            },
        )

        assert result.success is True
        assert result.data["session_id"] == "2a5c5d6e-0000-1111-2222-333344445555"
        assert "yookassa.ru" in result.data["session_url"]

    def test_create_payment_intent_error(self, adapter, mock_yookassa_api):
        """create_payment_intent should return error on failure."""
        error_resp = MagicMock()
        error_resp.status_code = 422
        error_resp.text = "Invalid amount"
        mock_yookassa_api.post.return_value = error_resp

        result = adapter.create_payment_intent(
            amount=Decimal("10.00"),
            currency="RUB",
            metadata={"success_url": "", "cancel_url": ""},
        )

        assert result.success is False
        assert "Invalid amount" in result.error

    def test_create_payment_intent_amount_format(self, adapter, mock_yookassa_api):
        """YooKassa uses string amounts with 2 decimals: Decimal('29.99') -> '29.99'."""
        payment_resp = MagicMock()
        payment_resp.status_code = 200
        payment_resp.json.return_value = {
            "id": "pay_amt",
            "status": "pending",
            "confirmation": {"confirmation_url": "https://yookassa.ru/pay"},
            "payment_method": {},
        }
        mock_yookassa_api.post.return_value = payment_resp

        adapter.create_payment_intent(
            amount=Decimal("29.99"),
            currency="RUB",
            metadata={"success_url": "", "cancel_url": ""},
        )

        # Check the payment data sent to YooKassa
        call_args = mock_yookassa_api.post.call_args
        payment_data = call_args.kwargs.get("json") or call_args[1].get("json")
        value = payment_data["amount"]["value"]
        assert value == "29.99"  # Not kopeks (2999)

    def test_create_payment_intent_uses_basic_auth(self, adapter, mock_yookassa_api):
        """Should use HTTP Basic Auth (shop_id, secret_key)."""
        payment_resp = MagicMock()
        payment_resp.status_code = 200
        payment_resp.json.return_value = {
            "id": "pay_auth",
            "status": "pending",
            "confirmation": {"confirmation_url": "https://yookassa.ru/pay"},
            "payment_method": {},
        }
        mock_yookassa_api.post.return_value = payment_resp

        adapter.create_payment_intent(
            amount=Decimal("100.00"),
            currency="RUB",
            metadata={"success_url": "", "cancel_url": ""},
        )

        call_args = mock_yookassa_api.post.call_args
        auth = call_args.kwargs.get("auth") or call_args[1].get("auth")
        assert auth == ("test_shop_123", "test_secret_456")

    def test_create_payment_intent_idempotency_key(self, adapter, mock_yookassa_api):
        """Should include Idempotence-Key header on POST requests."""
        payment_resp = MagicMock()
        payment_resp.status_code = 200
        payment_resp.json.return_value = {
            "id": "pay_idem",
            "status": "pending",
            "confirmation": {"confirmation_url": "https://yookassa.ru/pay"},
            "payment_method": {},
        }
        mock_yookassa_api.post.return_value = payment_resp

        adapter.create_payment_intent(
            amount=Decimal("50.00"),
            currency="RUB",
            metadata={"success_url": "", "cancel_url": ""},
        )

        call_args = mock_yookassa_api.post.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        assert "Idempotence-Key" in headers

    def test_create_payment_with_save_method(self, adapter, mock_yookassa_api):
        """Should include save_payment_method when metadata requests it."""
        payment_resp = MagicMock()
        payment_resp.status_code = 200
        payment_resp.json.return_value = {
            "id": "pay_save",
            "status": "pending",
            "confirmation": {"confirmation_url": "https://yookassa.ru/pay"},
            "payment_method": {"id": "pm_saved", "saved": True},
        }
        mock_yookassa_api.post.return_value = payment_resp

        result = adapter.create_payment_intent(
            amount=Decimal("99.00"),
            currency="RUB",
            metadata={
                "success_url": "",
                "cancel_url": "",
                "save_payment_method": True,
            },
        )

        call_args = mock_yookassa_api.post.call_args
        payment_data = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payment_data.get("save_payment_method") is True

    def test_capture_payment_success(self, adapter, mock_yookassa_api):
        """capture_payment should return payment status."""
        capture_resp = MagicMock()
        capture_resp.status_code = 200
        capture_resp.json.return_value = {
            "id": "pay_cap",
            "status": "succeeded",
            "amount": {"value": "100.00", "currency": "RUB"},
        }
        mock_yookassa_api.post.return_value = capture_resp

        result = adapter.capture_payment("pay_cap")

        assert result.success is True
        assert result.data["status"] == "succeeded"

    def test_capture_payment_error(self, adapter, mock_yookassa_api):
        """capture_payment should return error on failure."""
        error_resp = MagicMock()
        error_resp.status_code = 400
        error_resp.text = "Cannot capture"
        mock_yookassa_api.post.return_value = error_resp

        result = adapter.capture_payment("bad_pay")

        assert result.success is False

    def test_get_payment_status(self, adapter, mock_yookassa_api):
        """get_payment_status should return status, amount, currency."""
        status_resp = MagicMock()
        status_resp.status_code = 200
        status_resp.json.return_value = {
            "id": "pay_status",
            "status": "succeeded",
            "amount": {"value": "499.99", "currency": "RUB"},
            "metadata": {"invoice_id": "inv_abc"},
            "payment_method": {"id": "pm_123", "saved": True},
        }
        mock_yookassa_api.get.return_value = status_resp

        result = adapter.get_payment_status("pay_status")

        assert result.success is True
        assert result.data["status"] == "succeeded"
        assert result.data["amount_total"] == "499.99"
        assert result.data["currency"] == "RUB"
        assert result.data["invoice_id"] == "inv_abc"

    def test_get_payment_status_error(self, adapter, mock_yookassa_api):
        """get_payment_status should return error on failure."""
        error_resp = MagicMock()
        error_resp.status_code = 404
        error_resp.text = "Payment not found"
        mock_yookassa_api.get.return_value = error_resp

        result = adapter.get_payment_status("nonexistent")

        assert result.success is False

    def test_refund_full(self, adapter, mock_yookassa_api):
        """refund_payment without amount should issue full refund."""
        refund_resp = MagicMock()
        refund_resp.status_code = 200
        refund_resp.json.return_value = {"id": "ref_full", "status": "succeeded"}
        mock_yookassa_api.post.return_value = refund_resp

        result = adapter.refund_payment("pay_123")

        assert result.success is True
        assert result.data["refund_id"] == "ref_full"

    def test_refund_partial(self, adapter, mock_yookassa_api):
        """refund_payment with amount should include amount in request."""
        refund_resp = MagicMock()
        refund_resp.status_code = 200
        refund_resp.json.return_value = {"id": "ref_part", "status": "succeeded"}
        mock_yookassa_api.post.return_value = refund_resp

        result = adapter.refund_payment("pay_123", amount=Decimal("150.00"))

        assert result.success is True
        call_args = mock_yookassa_api.post.call_args
        refund_data = call_args.kwargs.get("json") or call_args[1].get("json")
        assert refund_data["amount"]["value"] == "150.00"

    def test_refund_includes_payment_id(self, adapter, mock_yookassa_api):
        """refund_payment should include payment_id in request body."""
        refund_resp = MagicMock()
        refund_resp.status_code = 200
        refund_resp.json.return_value = {"id": "ref_pid", "status": "succeeded"}
        mock_yookassa_api.post.return_value = refund_resp

        adapter.refund_payment("pay_abc")

        call_args = mock_yookassa_api.post.call_args
        refund_data = call_args.kwargs.get("json") or call_args[1].get("json")
        assert refund_data["payment_id"] == "pay_abc"

    def test_verify_webhook_valid(self, adapter):
        """verify_webhook_signature should return parsed event on valid HMAC."""
        import hashlib
        import hmac as hmac_mod

        payload = b'{"event": "payment.succeeded", "object": {}}'
        secret = "whsec_test"
        sig = hmac_mod.new(secret.encode(), payload, hashlib.sha256).hexdigest()

        result = adapter.verify_webhook_signature(payload, sig, secret)

        assert result["event"] == "payment.succeeded"

    def test_verify_webhook_invalid(self, adapter):
        """verify_webhook_signature should raise ValueError on invalid HMAC."""
        with pytest.raises(ValueError, match="Invalid YooKassa webhook signature"):
            adapter.verify_webhook_signature(
                b'{"event": "test"}',
                "bad_signature",
                "whsec_test",
            )

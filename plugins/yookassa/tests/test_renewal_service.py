"""Tests for YooKassaRenewalService."""
import pytest
from decimal import Decimal
from uuid import uuid4
from unittest.mock import MagicMock, patch, call


class TestYooKassaRenewalService:
    """Tests for YooKassaRenewalService.charge_saved_method."""

    def _make_subscription(self, provider_subscription_id="pm_saved_abc"):
        sub = MagicMock()
        sub.id = uuid4()
        sub.provider_subscription_id = provider_subscription_id
        return sub

    def _make_invoice(self, amount=Decimal("9.99"), currency="RUB"):
        inv = MagicMock()
        inv.id = uuid4()
        inv.amount = amount
        inv.currency = currency
        return inv

    def test_charge_saved_method_calls_payment_create(self, mocker):
        from plugins.yookassa.src.services.yookassa_renewal_service import (
            YooKassaRenewalService,
        )

        mock_yookassa = mocker.MagicMock()
        mocker.patch.dict(__import__("sys").modules, {"yookassa": mock_yookassa})

        sub = self._make_subscription("pm_test_123")
        inv = self._make_invoice(Decimal("19.99"), "RUB")

        svc = YooKassaRenewalService(shop_id="shop_1", secret_key="sk_1")
        svc.charge_saved_method(sub, inv)

        mock_yookassa.Payment.create.assert_called_once()

    def test_charge_saved_method_raises_if_no_payment_method(self):
        from plugins.yookassa.src.services.yookassa_renewal_service import (
            YooKassaRenewalService,
        )

        sub = self._make_subscription(provider_subscription_id=None)
        inv = self._make_invoice()

        svc = YooKassaRenewalService(shop_id="shop_1", secret_key="sk_1")
        with pytest.raises(ValueError, match="No saved payment method"):
            svc.charge_saved_method(sub, inv)

    def test_charge_saved_method_uses_idempotency_key(self, mocker):
        from plugins.yookassa.src.services.yookassa_renewal_service import (
            YooKassaRenewalService,
        )

        mock_yookassa = mocker.MagicMock()
        mocker.patch.dict(__import__("sys").modules, {"yookassa": mock_yookassa})

        sub = self._make_subscription("pm_idem_key")
        inv = self._make_invoice()

        svc = YooKassaRenewalService(shop_id="shop_1", secret_key="sk_1")
        svc.charge_saved_method(sub, inv)

        call_args = mock_yookassa.Payment.create.call_args
        idempotency_key = (
            call_args[0][1]
            if len(call_args[0]) > 1
            else call_args[1].get("idempotency_key") or call_args[0][1]
        )
        assert str(inv.id) == idempotency_key

    def test_charge_saved_method_uses_correct_amount(self, mocker):
        from plugins.yookassa.src.services.yookassa_renewal_service import (
            YooKassaRenewalService,
        )

        mock_yookassa = mocker.MagicMock()
        mocker.patch.dict(__import__("sys").modules, {"yookassa": mock_yookassa})

        sub = self._make_subscription("pm_amt_test")
        inv = self._make_invoice(Decimal("49.99"), "EUR")

        svc = YooKassaRenewalService(shop_id="shop_1", secret_key="sk_1")
        svc.charge_saved_method(sub, inv)

        call_args = mock_yookassa.Payment.create.call_args
        payload = call_args[0][0]
        assert payload["amount"]["value"] == "49.99"
        assert payload["amount"]["currency"] == "EUR"
        assert payload["payment_method_id"] == "pm_amt_test"

"""PayoutProvider contract tests (S79 D1).

Core defines the payout capability as a sibling ABC next to
``PaymentProviderPlugin`` and never calls it — the withdraw plugin
discovers implementers via ``PluginManager.get_enabled_plugins()`` +
``isinstance``. These specs pin the exact surface (ISP: three methods,
nothing more) and the Liskov semantics (``create_payout`` returns a
``PayoutResult`` or raises the typed ``PayoutError``).
"""
import dataclasses
from decimal import Decimal

import pytest

from vbwd.plugins.payment_provider import (
    PayoutError,
    PayoutProvider,
    PayoutResult,
)


class ConformingPayoutProvider(PayoutProvider):
    """Minimal contract-honouring implementer used by these specs."""

    def get_payout_destination_schema(self) -> list:
        return [{"name": "email", "type": "email", "label_key": "withdraw.email"}]

    def create_payout(
        self,
        amount: Decimal,
        currency: str,
        destination: dict,
        reference_id: str,
    ) -> PayoutResult:
        return PayoutResult(provider_payout_id="payout-1", status="processing")

    def get_payout_status(self, provider_payout_id: str) -> str:
        return "completed"


class TestPayoutProviderContract:
    def test_payout_provider_is_abstract(self):
        with pytest.raises(TypeError):
            PayoutProvider()  # type: ignore[abstract]

    def test_contract_declares_exactly_the_three_payout_methods(self):
        assert PayoutProvider.__abstractmethods__ == {
            "get_payout_destination_schema",
            "create_payout",
            "get_payout_status",
        }

    def test_conforming_implementer_passes_isinstance(self):
        provider = ConformingPayoutProvider()
        assert isinstance(provider, PayoutProvider)

    def test_create_payout_returns_payout_result(self):
        provider = ConformingPayoutProvider()
        result = provider.create_payout(
            amount=Decimal("10.00"),
            currency="EUR",
            destination={"email": "user@example.com"},
            reference_id="ref-1",
        )
        assert result.provider_payout_id == "payout-1"
        assert result.status == "processing"


class TestPayoutResult:
    def test_is_a_dataclass_with_id_and_status(self):
        assert dataclasses.is_dataclass(PayoutResult)
        field_names = {field.name for field in dataclasses.fields(PayoutResult)}
        assert field_names == {"provider_payout_id", "status"}


class TestPayoutError:
    def test_is_a_typed_exception(self):
        assert issubclass(PayoutError, Exception)
        with pytest.raises(PayoutError):
            raise PayoutError("provider rejected the payout")

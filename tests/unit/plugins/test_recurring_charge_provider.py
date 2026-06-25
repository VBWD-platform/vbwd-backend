"""RecurringChargeProvider contract tests (S103.0).

Core defines the off-session recurring-charge capability as a sibling ABC
next to ``PaymentProviderPlugin`` / ``PayoutProvider`` and never calls it —
the subscription plugin discovers implementers via
``PluginManager.get_enabled_plugins()`` + ``isinstance`` (mirroring withdraw's
``payout_provider_resolver``). These specs pin the exact surface (ISP: one
method) and the Liskov semantics: ``charge_saved_method`` returns a
``ChargeResult`` (``success=True`` after the provider captures the invoice, or
``success=False`` with an ``error`` on a declined/insufficient charge) — it
never leaks a provider-specific exception to the caller.
"""
import dataclasses
from uuid import uuid4

import pytest

from vbwd.plugins.payment_provider import (
    ChargeResult,
    RecurringChargeProvider,
)


class ConformingRecurringChargeProvider(RecurringChargeProvider):
    """Minimal contract-honouring implementer used by these specs."""

    def charge_saved_method(self, *, user_id, invoice) -> ChargeResult:
        return ChargeResult(success=True, provider_reference="ref-1")


class TestRecurringChargeProviderContract:
    def test_recurring_charge_provider_is_abstract(self):
        with pytest.raises(TypeError):
            RecurringChargeProvider()  # type: ignore[abstract]

    def test_contract_declares_exactly_the_one_charge_method(self):
        assert RecurringChargeProvider.__abstractmethods__ == {
            "charge_saved_method",
        }

    def test_conforming_implementer_passes_isinstance(self):
        provider = ConformingRecurringChargeProvider()
        assert isinstance(provider, RecurringChargeProvider)

    def test_charge_saved_method_returns_charge_result(self):
        provider = ConformingRecurringChargeProvider()
        result = provider.charge_saved_method(
            user_id=uuid4(),
            invoice=object(),
        )
        assert result.success is True
        assert result.provider_reference == "ref-1"


class TestChargeResult:
    def test_is_a_dataclass_with_the_expected_fields(self):
        assert dataclasses.is_dataclass(ChargeResult)
        field_names = {field.name for field in dataclasses.fields(ChargeResult)}
        assert field_names == {
            "success",
            "provider_reference",
            "transaction_id",
            "error",
        }

    def test_success_is_required_and_the_rest_default_to_empty(self):
        result = ChargeResult(success=False)
        assert result.success is False
        assert result.provider_reference == ""
        assert result.transaction_id == ""
        assert result.error == ""

    def test_failure_carries_an_error_message(self):
        result = ChargeResult(success=False, error="insufficient token balance")
        assert result.success is False
        assert result.error == "insufficient token balance"

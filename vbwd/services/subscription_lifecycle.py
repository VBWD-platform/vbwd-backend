"""Generic subscription-lifecycle port — payment plugins stay subscription-free.

Payment providers (stripe/paypal/yookassa) used to reach into the subscription
repository from their webhook handlers to link/renew/cancel/fail recurring
subscriptions. Core now defines this narrow write port; the subscription plugin
supplies the implementation. When no provider is registered (subscription plugin
disabled) every method is a no-op — a payment install with no plan concept has
no subscriptions to update.
"""
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional, Union
from uuid import UUID


class ISubscriptionLifecycle(ABC):
    """Narrow write port (ISP) — only what payment webhooks need.

    Read-side "is this line item recurring / its billing spec" is *not* here —
    that lives in the extensible line-item registry, so any plugin can declare
    a recurring line-item type.
    """

    @abstractmethod
    def link_provider_subscription(
        self, invoice_id: UUID, provider_subscription_id: str
    ) -> None:
        """After initial checkout, record the provider's subscription id on the
        domain subscription referenced by the invoice's subscription line item."""

    @abstractmethod
    def record_provider_renewal(
        self,
        provider: str,
        provider_subscription_id: str,
        amount: Union[Decimal, str],
        currency: str,
        provider_reference: str,
    ) -> Optional[UUID]:
        """Create a renewal invoice for the matching subscription and return its
        id (so the caller can emit payment-captured), or None if no match /
        already processed."""

    @abstractmethod
    def cancel_by_provider_subscription_id(
        self, provider: str, provider_subscription_id: str, reason: Optional[str] = None
    ) -> None:
        """Cancel the subscription identified by the provider's subscription id."""

    @abstractmethod
    def mark_provider_payment_failed(
        self, provider: str, provider_subscription_id: str, error_message: str
    ) -> None:
        """Flag a failed recurring charge for the matching subscription."""

    @abstractmethod
    def mark_invoice_payment_failed(
        self,
        invoice_id: UUID,
        provider: str,
        error_message: str,
        error_code: str = "payment_failed",
    ) -> None:
        """Flag payment failure for the subscription on an invoice (when the
        provider keys the failure by invoice, not provider subscription id)."""


class _NullSubscriptionLifecycle(ISubscriptionLifecycle):
    """Used when the subscription plugin is disabled — every method no-ops."""

    def link_provider_subscription(self, invoice_id, provider_subscription_id) -> None:
        return None

    def record_provider_renewal(
        self, provider, provider_subscription_id, amount, currency, provider_reference
    ) -> Optional[UUID]:
        return None

    def cancel_by_provider_subscription_id(
        self, provider, provider_subscription_id, reason=None
    ) -> None:
        return None

    def mark_provider_payment_failed(
        self, provider, provider_subscription_id, error_message
    ) -> None:
        return None

    def mark_invoice_payment_failed(
        self, invoice_id, provider, error_message, error_code="payment_failed"
    ) -> None:
        return None


_lifecycle: Optional[ISubscriptionLifecycle] = None


def register_subscription_lifecycle(lifecycle: ISubscriptionLifecycle) -> None:
    """Called by the subscription plugin on enable."""
    global _lifecycle
    _lifecycle = lifecycle


def clear_subscription_lifecycle() -> None:
    """Reset to the null default (plugin disable / test teardown)."""
    global _lifecycle
    _lifecycle = None


def resolve_subscription_lifecycle() -> ISubscriptionLifecycle:
    """The registered lifecycle, or the no-op null default."""
    return _lifecycle if _lifecycle is not None else _NullSubscriptionLifecycle()

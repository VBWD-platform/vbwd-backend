"""Payment provider plugin interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from decimal import Decimal
from uuid import UUID
from enum import Enum
from vbwd.plugins.base import BasePlugin


class PaymentStatus(Enum):
    """Payment status."""

    PENDING = "pending"
    PROCESSING = "processing"
    AUTHORIZED = "authorized"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class PaymentResult:
    """Payment transaction result."""

    def __init__(
        self,
        success: bool,
        transaction_id: Optional[str] = None,
        status: PaymentStatus = PaymentStatus.PENDING,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.transaction_id = transaction_id
        self.status = status
        self.error_message = error_message
        self.metadata = metadata or {}


class PayoutError(Exception):
    """Typed payout failure raised by ``PayoutProvider.create_payout``.

    Liskov: every implementer raises exactly this (no provider-specific
    exception leaks to the caller); the caller decides how to react
    (the withdraw plugin marks the request failed and refunds).
    """


@dataclass
class PayoutResult:
    """Result of an accepted payout."""

    provider_payout_id: str
    status: str


class PayoutProvider(ABC):
    """
    Opt-in payout capability for payment provider plugins (S79 D1).

    Core only defines this contract and never calls it — the withdraw
    plugin discovers implementers via
    ``PluginManager.get_enabled_plugins()`` + ``isinstance``. Narrow
    port (ISP): exactly the three methods below. A provider opts in by
    additionally inheriting this ABC, e.g.
    ``class PayPalPlugin(PaymentProviderPlugin, PayoutProvider)``.
    """

    @abstractmethod
    def get_payout_destination_schema(self) -> List[Dict[str, Any]]:
        """
        Describe the destination form fields for this provider.

        Returns:
            List of field descriptors, each with at least
            ``name`` / ``type`` / ``label_key``
            (e.g. ``[{"name": "email", "type": "email",
            "label_key": "withdraw.paypal_email"}]``).
        """
        pass

    @abstractmethod
    def create_payout(
        self,
        amount: Decimal,
        currency: str,
        destination: Dict[str, Any],
        reference_id: str,
    ) -> PayoutResult:
        """
        Send money to the given destination.

        Args:
            amount: Payout amount in ``currency``
            currency: Currency code (ISO 4217)
            destination: Provider-specific destination, shaped per
                :meth:`get_payout_destination_schema`
            reference_id: Caller's idempotency/audit reference
                (the withdraw request id)

        Returns:
            PayoutResult with the provider's payout id and status

        Raises:
            PayoutError: If the provider rejects or fails the payout
        """
        pass

    @abstractmethod
    def get_payout_status(self, provider_payout_id: str) -> str:
        """
        Fetch the provider-side status of a previously created payout.

        Args:
            provider_payout_id: Id returned in :class:`PayoutResult`

        Returns:
            Provider-neutral status string (e.g. "processing",
            "completed", "failed")
        """
        pass


class PaymentProviderPlugin(BasePlugin):
    """
    Abstract base class for payment provider plugins.

    Payment providers (Stripe, PayPal, etc.) must inherit from this class.
    Supports both immediate charge and authorize-then-capture flows.
    """

    @abstractmethod
    def create_payment_intent(
        self,
        amount: Decimal,
        currency: str,
        subscription_id: UUID,
        user_id: UUID,
        metadata: Optional[Dict[str, Any]] = None,
        capture: bool = True,
    ) -> PaymentResult:
        """
        Create payment intent/session.

        Args:
            amount: Payment amount
            currency: Currency code (ISO 4217)
            subscription_id: Subscription UUID
            user_id: User UUID
            metadata: Optional metadata
            capture: If True, charge immediately. If False, authorize only (hold).

        Returns:
            PaymentResult with transaction details
        """
        pass

    @abstractmethod
    def capture_payment(
        self,
        payment_id: str,
        amount: Optional[Decimal] = None,
    ) -> PaymentResult:
        """
        Capture a previously authorized payment.

        Args:
            payment_id: Provider-specific payment/intent ID
            amount: Optional partial capture amount. None = full amount.

        Returns:
            PaymentResult with capture status
        """
        pass

    @abstractmethod
    def release_authorization(
        self,
        payment_id: str,
    ) -> PaymentResult:
        """
        Release/void a previously authorized payment hold.

        Args:
            payment_id: Provider-specific payment/intent ID

        Returns:
            PaymentResult with void status
        """
        pass

    @abstractmethod
    def process_payment(
        self,
        payment_intent_id: str,
        payment_method: str,
    ) -> PaymentResult:
        """
        Process payment with given method.

        Args:
            payment_intent_id: Payment intent/session ID
            payment_method: Payment method identifier

        Returns:
            PaymentResult with status
        """
        pass

    @abstractmethod
    def refund_payment(
        self,
        transaction_id: str,
        amount: Optional[Decimal] = None,
    ) -> PaymentResult:
        """
        Refund a payment (full or partial).

        Args:
            transaction_id: Original transaction ID
            amount: Optional partial refund amount (None = full refund)

        Returns:
            PaymentResult with refund status
        """
        pass

    @abstractmethod
    def verify_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> bool:
        """
        Verify webhook signature.

        Args:
            payload: Webhook payload
            signature: Webhook signature header

        Returns:
            True if signature is valid
        """
        pass

    @abstractmethod
    def handle_webhook(
        self,
        payload: Dict[str, Any],
    ) -> None:
        """
        Handle webhook event from payment provider.

        Args:
            payload: Parsed webhook payload
        """
        pass

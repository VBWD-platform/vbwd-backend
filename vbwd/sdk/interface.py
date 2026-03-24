"""SDK adapter interfaces and data classes."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import Dict, Any, Optional


@dataclass
class SDKConfig:
    """Configuration for SDK adapters.

    Attributes:
        api_key: API key for authentication
        api_secret: Optional API secret
        sandbox: Whether to use sandbox/test mode (default: True)
        timeout: Request timeout in seconds (default: 30)
        max_retries: Max retry attempts for transient errors (default: 3)
    """

    api_key: str
    api_secret: Optional[str] = None
    sandbox: bool = True
    timeout: int = 30
    max_retries: int = 3


@dataclass
class SDKResponse:
    """Standardized response from SDK operations.

    Attributes:
        success: Whether operation succeeded
        data: Response data (on success)
        error: Error message (on failure)
        error_code: Provider-specific error code
    """

    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert response to dictionary."""
        return asdict(self)


class ISDKAdapter(ABC):
    """Interface for payment provider SDK adapters.

    All payment providers must implement this interface.
    Liskov Substitution: Any ISDKAdapter can be used interchangeably.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return provider name (e.g., 'stripe', 'paypal')."""
        ...

    @abstractmethod
    def create_payment_intent(
        self,
        amount: Decimal,
        currency: str,
        metadata: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> SDKResponse:
        """Create payment intent/order.

        Args:
            amount: Payment amount
            currency: ISO currency code (e.g., 'USD')
            metadata: Additional metadata
            idempotency_key: Optional key for idempotent requests

        Returns:
            SDKResponse with payment_intent_id in data
        """
        ...

    @abstractmethod
    def capture_payment(
        self, payment_intent_id: str, idempotency_key: Optional[str] = None
    ) -> SDKResponse:
        """Capture authorized payment.

        Args:
            payment_intent_id: ID of payment intent to capture
            idempotency_key: Optional key for idempotent requests

        Returns:
            SDKResponse with capture status
        """
        ...

    @abstractmethod
    def release_authorization(self, payment_intent_id: str) -> SDKResponse:
        """Release (void) an authorized payment.

        Args:
            payment_intent_id: ID of payment intent to cancel

        Returns:
            SDKResponse with release status
        """
        ...

    @abstractmethod
    def refund_payment(
        self,
        payment_intent_id: str,
        amount: Optional[Decimal] = None,
        idempotency_key: Optional[str] = None,
    ) -> SDKResponse:
        """Refund payment.

        Args:
            payment_intent_id: ID of payment intent to refund
            amount: Partial refund amount (None for full refund)
            idempotency_key: Optional key for idempotent requests

        Returns:
            SDKResponse with refund details
        """
        ...

    @abstractmethod
    def get_payment_status(self, payment_intent_id: str) -> SDKResponse:
        """Get current payment status.

        Args:
            payment_intent_id: ID of payment intent

        Returns:
            SDKResponse with status in data
        """
        ...

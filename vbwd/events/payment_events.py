"""Payment domain events."""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Dict, Any
from uuid import UUID
from vbwd.events.domain import DomainEvent


@dataclass
class CheckoutInitiatedEvent:
    """User initiated checkout for a tariff plan.

    Emitted when user starts the checkout process.
    Handler should create payment intent via SDK adapter.
    """

    user_id: UUID
    tarif_plan_id: UUID
    provider: str
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    return_url: Optional[str] = None
    cancel_url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    name: str = field(default="checkout.initiated", init=False)


@dataclass
class PaymentAuthorizedEvent(DomainEvent):
    """Payment authorized (funds held, not yet captured).

    Emitted when payment provider confirms card authorization.
    Handler sets invoice to AUTHORIZED status but does NOT activate items.
    Items are activated only when PaymentCapturedEvent fires (after capture).
    """

    invoice_id: Optional[UUID] = None
    payment_reference: Optional[str] = None
    amount: Optional[str] = None
    currency: str = "USD"
    provider: Optional[str] = None
    payment_intent_id: Optional[str] = None

    def __post_init__(self):
        self.name = "payment.authorized"
        super().__post_init__()


@dataclass
class PaymentCapturedEvent(DomainEvent):
    """Payment successfully captured.

    Emitted when payment is confirmed (webhook or admin action).
    Handler activates all pending items on the invoice:
    - Subscription → active
    - Token bundles → tokens credited
    - Add-ons → active
    """

    invoice_id: Optional[UUID] = None
    payment_reference: Optional[str] = None
    amount: Optional[str] = None
    currency: str = "USD"
    # Legacy fields for backward compatibility
    subscription_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    transaction_id: Optional[str] = None
    provider: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.name = "payment.captured"
        super().__post_init__()


@dataclass
class PaymentFailedEvent:
    """Payment failed.

    Emitted when payment provider reports payment failure.
    Handler should update subscription status and notify user.
    """

    subscription_id: UUID
    user_id: UUID
    error_code: str
    error_message: str
    provider: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    name: str = field(default="payment.failed", init=False)


@dataclass
class PaymentRefundedEvent(DomainEvent):
    """Payment refunded.

    Emitted when a refund is completed (admin action or webhook).
    Handler reverses all activated items on the invoice:
    - Subscription → cancelled
    - Token bundles → tokens debited
    - Add-ons → cancelled
    """

    invoice_id: Optional[UUID] = None
    refund_reference: Optional[str] = None
    amount: Optional[str] = None
    currency: str = "USD"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.name = "payment.refunded"
        super().__post_init__()


@dataclass
class RefundReversedEvent(DomainEvent):
    """Refund reversed/cancelled by payment provider.

    Emitted when a previously completed refund is cancelled or reversed.
    Handler restores all items on the invoice:
    - Invoice → PAID
    - Subscription → re-activated
    - Token bundles → tokens re-credited
    - Add-ons → re-activated
    """

    invoice_id: Optional[UUID] = None
    reason: str = ""
    provider: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.name = "refund.reversed"
        super().__post_init__()


@dataclass
class SubscriptionCancelledEvent(DomainEvent):
    """Subscription cancelled by provider (webhook) or admin action.

    Handler marks subscription as CANCELLED.
    """

    subscription_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    reason: str = ""
    provider: Optional[str] = None

    def __post_init__(self):
        self.name = "subscription.cancelled"
        super().__post_init__()


@dataclass
class RefundRequestedEvent:
    """Refund requested.

    Emitted when a refund is requested for a transaction.
    Handler should call SDK adapter to process refund.
    """

    transaction_id: str
    subscription_id: UUID
    reason: str
    provider: Optional[str] = None
    amount: Optional[Decimal] = None  # None for full refund
    metadata: Dict[str, Any] = field(default_factory=dict)
    name: str = field(default="refund.requested", init=False)

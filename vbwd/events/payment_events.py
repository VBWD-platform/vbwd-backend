"""Generic payment domain events.

Core stays domain-neutral: these events carry only ``invoice_id`` plus a
free-form ``metadata`` dict. Any plugin that owns the activated items (plans,
add-ons, bookings, tokens, ...) derives its own linkage from the invoice's line
items via the line-item registry — core never names a plugin domain here.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from uuid import UUID
from vbwd.events.domain import DomainEvent


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
    Handler activates all pending items on the invoice via the line-item
    registry; core does not know which item types exist.
    """

    invoice_id: Optional[UUID] = None
    payment_reference: Optional[str] = None
    amount: Optional[str] = None
    currency: str = "USD"
    user_id: Optional[UUID] = None
    transaction_id: Optional[str] = None
    provider: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.name = "payment.captured"
        super().__post_init__()


@dataclass
class PaymentRefundedEvent(DomainEvent):
    """Payment refunded.

    Emitted when a refund is completed (admin action or webhook).
    Handler reverses all activated items on the invoice via the line-item
    registry.
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
    Handler restores all items on the invoice via the line-item registry and
    sets the invoice back to PAID.
    """

    invoice_id: Optional[UUID] = None
    reason: str = ""
    provider: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.name = "refund.reversed"
        super().__post_init__()

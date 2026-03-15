"""Event system for plugin communication."""
from src.events.domain import (
    DomainEvent,
    EventResult,
    IEventHandler,
    DomainEventDispatcher,
)
from src.events.checkout_events import (
    CheckoutRequestedEvent,
    CheckoutCompletedEvent,
    CheckoutFailedEvent,
)
from src.events.payment_events import (
    PaymentCapturedEvent,
    PaymentFailedEvent,
)
from src.events.bus import EventBus, event_bus

__all__ = [
    "DomainEvent",
    "EventResult",
    "IEventHandler",
    "DomainEventDispatcher",
    "CheckoutRequestedEvent",
    "CheckoutCompletedEvent",
    "CheckoutFailedEvent",
    "PaymentCapturedEvent",
    "PaymentFailedEvent",
    "EventBus",
    "event_bus",
]

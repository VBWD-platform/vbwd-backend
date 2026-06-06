"""Event system for plugin communication."""
from vbwd.events.domain import (
    DomainEvent,
    EventResult,
    IEventHandler,
    DomainEventDispatcher,
)
from vbwd.events.payment_events import (
    PaymentCapturedEvent,
)
from vbwd.events.bus import EventBus, event_bus

__all__ = [
    "DomainEvent",
    "EventResult",
    "IEventHandler",
    "DomainEventDispatcher",
    "PaymentCapturedEvent",
    "EventBus",
    "event_bus",
]

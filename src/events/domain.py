"""Domain event system with handlers and results."""
from dataclasses import dataclass
from datetime import datetime
from src.utils.datetime_utils import utcnow
from typing import Any, Dict, Optional, List
from abc import ABC, abstractmethod
from src.events.dispatcher import Event as BaseEvent


@dataclass
class DomainEvent(BaseEvent):
    """
    Domain event class with metadata.

    Extends base Event with timestamp and metadata for domain events.
    """

    timestamp: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Initialize default values after dataclass initialization."""
        if self.timestamp is None:
            self.timestamp = utcnow()
        if self.metadata is None:
            self.metadata = {}


@dataclass
class EventResult:
    """
    Result of event handling.

    Encapsulates success/failure status and optional data or error.
    """

    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    error_type: Optional[str] = None

    @classmethod
    def success_result(cls, data: Any = None) -> "EventResult":
        """Create successful result."""
        return cls(success=True, data=data)

    @classmethod
    def error_result(
        cls, error: str, error_type: str = "handler_error"
    ) -> "EventResult":
        """Create failed result."""
        return cls(success=False, error=error, error_type=error_type)

    @classmethod
    def no_handler(cls) -> "EventResult":
        """Create no handler result."""
        return cls(
            success=False,
            error="No handler registered for event",
            error_type="no_handler",
        )

    @classmethod
    def combine(cls, results: List["EventResult"]) -> "EventResult":
        """
        Combine multiple results.

        Returns success if all results succeeded, failure otherwise.
        """
        if not results:
            return cls.success_result()

        # If any failed, return combined failure
        failed = [r for r in results if not r.success]
        if failed:
            errors = [r.error for r in failed if r.error]
            # Use error_type from first failed result
            error_type = (
                failed[0].error_type if failed[0].error_type else "handler_error"
            )
            return cls.error_result("; ".join(errors), error_type=error_type)

        # All succeeded, combine data
        data = [r.data for r in results if r.data is not None]
        return cls.success_result(data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "error_type": self.error_type,
        }


class IEventHandler(ABC):
    """
    Interface for event handlers.

    All domain event handlers must implement this interface.
    """

    @abstractmethod
    def can_handle(self, event: DomainEvent) -> bool:
        """
        Check if this handler can handle the given event.

        Args:
            event: The event to check

        Returns:
            True if handler can handle this event
        """
        pass

    @abstractmethod
    def handle(self, event: DomainEvent) -> EventResult:
        """
        Handle the event.

        Args:
            event: The event to handle

        Returns:
            EventResult with success/failure status
        """
        pass


class DomainEventDispatcher:
    """
    Domain event dispatcher with handler interface support.

    Extends base EventDispatcher with domain event handling.

    After running typed ``IEventHandler`` objects, ``emit()`` also forwards
    the event to the module-level ``event_bus`` singleton so plugin subscribers
    receive all domain events without modifying any core emit site.

    Pass ``event_bus=None`` to disable the bridge (useful in unit tests that
    want to test handlers in isolation without side-effects on the bus).
    """

    def __init__(self, event_bus=None):
        self._handlers: Dict[str, List[IEventHandler]] = {}
        # Accept explicit injection; fall back to the module singleton lazily
        # to avoid a circular import at class-definition time.
        self._event_bus = event_bus  # None → resolved lazily in emit()

    def register(self, event_name: str, handler: IEventHandler) -> None:
        """
        Register event handler.

        Args:
            event_name: Name of event to handle
            handler: Handler instance
        """
        if event_name not in self._handlers:
            self._handlers[event_name] = []

        self._handlers[event_name].append(handler)

    def has_handler(self, event_name: str) -> bool:
        """Check if event has any handlers."""
        return event_name in self._handlers and len(self._handlers[event_name]) > 0

    def emit(self, event: DomainEvent) -> EventResult:
        """
        Emit event to all registered handlers, then forward to EventBus.

        Typed ``IEventHandler`` objects run first (core behaviour unchanged).
        Afterwards, ``event_bus.publish(event.name, event.data)`` is called so
        plugin callbacks also receive the event — no call-site changes needed.

        Args:
            event: Domain event to emit

        Returns:
            Combined EventResult from all handlers
        """
        results = []

        if event.name in self._handlers:
            for handler in self._handlers[event.name]:
                try:
                    if handler.can_handle(event):
                        result = handler.handle(event)
                        results.append(result)
                except Exception as e:
                    results.append(
                        EventResult.error_result(
                            error=str(e), error_type="handler_exception"
                        )
                    )

        # Bridge to EventBus (lazy import avoids circular dependency)
        bus = self._event_bus
        if bus is None:
            try:
                from src.events.bus import event_bus as _bus

                bus = _bus
            except Exception:
                bus = None
        if bus is not None:
            try:
                bus.publish(event.name, event.data or {})
            except Exception as exc:  # noqa: BLE001
                import logging

                logging.getLogger(__name__).warning(
                    "[domain] EventBus.publish failed for %s: %s", event.name, exc
                )

        if not results:
            return EventResult.no_handler()

        return EventResult.combine(results)

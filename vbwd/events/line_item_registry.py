"""Line item handler registry — plugins register handlers for their line item types.

Core delegates invoice line item processing (activation, reversal, restoration)
to registered handlers via this registry. Each plugin registers its own handler
at startup via BasePlugin.register_line_item_handlers().
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, List, Tuple
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class RecurringBillingSpec:
    """How a payment provider should set up a recurring charge for a line item.

    Provider-agnostic: ``billing_period`` is a domain term (e.g. "MONTHLY")
    each provider maps to its own interval vocabulary.
    """

    name: str
    billing_period: str


@dataclass
class LineItemContext:
    """Context passed to line item handlers during processing."""

    invoice: Any
    user_id: UUID
    container: Any


@dataclass
class LineItemResult:
    """Result from a line item handler operation."""

    success: bool
    data: dict = field(default_factory=dict)
    error: Optional[str] = None
    skipped: bool = False

    @classmethod
    def skip(cls) -> "LineItemResult":
        """No handler matched this line item."""
        return cls(success=True, skipped=True)

    @classmethod
    def from_error(cls, error: str) -> "LineItemResult":
        """Handler raised an exception."""
        return cls(success=False, error=error)


class ILineItemHandler(ABC):
    """Interface for plugin line item handlers.

    Plugins implement this to handle their own invoice line item types
    during payment capture, refund, and refund reversal.
    """

    @abstractmethod
    def can_handle_line_item(self, line_item: Any, context: LineItemContext) -> bool:
        """Return True if this handler should process this line item."""

    @abstractmethod
    def activate_line_item(
        self, line_item: Any, context: LineItemContext
    ) -> LineItemResult:
        """Activate a line item after payment capture."""

    @abstractmethod
    def reverse_line_item(
        self, line_item: Any, context: LineItemContext
    ) -> LineItemResult:
        """Reverse a line item on refund."""

    @abstractmethod
    def restore_line_item(
        self, line_item: Any, context: LineItemContext
    ) -> LineItemResult:
        """Restore a line item on refund reversal."""

    def resolve_catalog_item_id(self, line_item: Any) -> Optional[str]:
        """Resolve the catalog entity id for a line item this handler owns.

        Non-abstract (ISP): handlers with no catalog mapping inherit the
        None default. A handler must return None for line items it does not
        own, so the registry can poll handlers without a processing context.
        """
        return None

    def resolve_catalog_entity_ref(self, line_item: Any) -> Optional[Tuple[str, str]]:
        """Resolve the source ``(entity_type, catalog_id)`` for a line this owns.

        Used by the invoice line-item snapshot (S77): the snapshot must know
        BOTH the source's registered ``entity_type`` (e.g. ``"tarif_plan"``,
        ``"shop_product"``) and its catalog id so it can copy the source's
        tags/custom-fields onto the line. Non-abstract (ISP): a handler that
        maps no source entity inherits the ``None`` default, and a handler must
        return ``None`` for line items it does not own so the registry can poll
        handlers without a processing context.
        """
        return None

    def is_recurring_line_item(self, line_item: Any) -> bool:
        """Whether this line item represents a recurring charge.

        Non-abstract (ISP): non-recurring concerns (e.g. token bundles)
        inherit the False default. A handler returns False for line items
        it does not own.
        """
        return False

    def recurring_billing_spec(self, line_item: Any) -> Optional[RecurringBillingSpec]:
        """Billing spec for a recurring line item this handler owns, else None.

        Lets a payment provider set up the recurring charge (display name +
        billing period) without knowing the line item's domain. Non-abstract
        (ISP): one-off concerns inherit None; a handler that owns the item but
        treats it as one-off also returns None (so providers charge it once).
        """
        return None


class LineItemHandlerRegistry:
    """Registry of line item handlers. First matching handler wins."""

    def __init__(self) -> None:
        self._handlers: List[ILineItemHandler] = []

    @property
    def handlers(self) -> List[ILineItemHandler]:
        return list(self._handlers)

    def register(self, handler: ILineItemHandler) -> None:
        """Register a handler. Order matters — first match wins."""
        self._handlers.append(handler)

    def clear(self) -> None:
        """Remove all handlers. Used in tests to reset singleton state."""
        self._handlers.clear()

    def process_activation(
        self, line_item: Any, context: LineItemContext
    ) -> LineItemResult:
        """Delegate line item activation to the first matching handler."""
        return self._dispatch(line_item, context, "activate_line_item")

    def process_reversal(
        self, line_item: Any, context: LineItemContext
    ) -> LineItemResult:
        """Delegate line item reversal to the first matching handler."""
        return self._dispatch(line_item, context, "reverse_line_item")

    def process_restoration(
        self, line_item: Any, context: LineItemContext
    ) -> LineItemResult:
        """Delegate line item restoration to the first matching handler."""
        return self._dispatch(line_item, context, "restore_line_item")

    def resolve_catalog_item_id(self, line_item: Any) -> Optional[str]:
        """First handler that owns this line item resolves its catalog id.

        Context-free (called from serialization, not payment processing).
        Each handler self-filters by item type and returns None when the
        line item is not its own.
        """
        for handler in self._handlers:
            try:
                resolved = handler.resolve_catalog_item_id(line_item)
            except Exception as exception:
                logger.warning(
                    "[line-item-registry] %s.resolve_catalog_item_id raised %s: %s",
                    type(handler).__name__,
                    type(exception).__name__,
                    exception,
                )
                continue
            if resolved is not None:
                return resolved
        return None

    def resolve_catalog_entity_ref(self, line_item: Any) -> Optional[Tuple[str, str]]:
        """First handler that owns this line resolves its source entity ref.

        Context-free (called from the invoice snapshot at line creation, not
        payment processing). Each handler self-filters by item type and returns
        ``None`` when the line item is not its own.
        """
        for handler in self._handlers:
            try:
                ref = handler.resolve_catalog_entity_ref(line_item)
            except Exception as exception:
                logger.warning(
                    "[line-item-registry] %s.resolve_catalog_entity_ref raised %s: %s",
                    type(handler).__name__,
                    type(exception).__name__,
                    exception,
                )
                continue
            if ref is not None:
                return ref
        return None

    def is_recurring_line_item(self, line_item: Any) -> bool:
        """True if any handler considers this line item a recurring charge."""
        for handler in self._handlers:
            try:
                if handler.is_recurring_line_item(line_item):
                    return True
            except Exception as exception:
                logger.warning(
                    "[line-item-registry] %s.is_recurring_line_item raised %s: %s",
                    type(handler).__name__,
                    type(exception).__name__,
                    exception,
                )
                continue
        return False

    def recurring_billing_spec(self, line_item: Any) -> Optional[RecurringBillingSpec]:
        """First handler that owns this recurring line item supplies its spec.

        Returns None for one-off line items (token bundles, shop items, …) so
        payment providers charge them once instead of as a subscription.
        """
        for handler in self._handlers:
            try:
                spec = handler.recurring_billing_spec(line_item)
            except Exception as exception:
                logger.warning(
                    "[line-item-registry] %s.recurring_billing_spec raised %s: %s",
                    type(handler).__name__,
                    type(exception).__name__,
                    exception,
                )
                continue
            if spec is not None:
                return spec
        return None

    def _dispatch(
        self, line_item: Any, context: LineItemContext, method_name: str
    ) -> LineItemResult:
        """Find matching handler and call the specified method."""
        for handler in self._handlers:
            if handler.can_handle_line_item(line_item, context):
                try:
                    method = getattr(handler, method_name)
                    return method(line_item, context)
                except Exception as exception:
                    logger.warning(
                        "[line-item-registry] %s.%s raised %s: %s",
                        type(handler).__name__,
                        method_name,
                        type(exception).__name__,
                        exception,
                    )
                    return LineItemResult.from_error(str(exception))

        logger.debug(
            "[line-item-registry] No handler matched line item %s",
            getattr(line_item, "id", "?"),
        )
        return LineItemResult.skip()


# Module-level singleton — plugins register at startup, handlers use at runtime
line_item_registry = LineItemHandlerRegistry()

"""S5a — recurrence moved off core into the line-item registry.

`payment_route_helpers.determine_session_mode` no longer imports
subscription models; it asks the registry. Core handlers inherit the
non-recurring default.
"""
import inspect
from types import SimpleNamespace

from vbwd.events.line_item_registry import (
    ILineItemHandler,
    LineItemHandlerRegistry,
)
from vbwd.models.enums import LineItemType


class _RecurringOwner(ILineItemHandler):
    def __init__(self, owned_type):
        self._owned_type = owned_type

    def can_handle_line_item(self, line_item, context):
        return line_item.item_type == self._owned_type

    def activate_line_item(self, line_item, context):  # pragma: no cover
        ...

    def reverse_line_item(self, line_item, context):  # pragma: no cover
        ...

    def restore_line_item(self, line_item, context):  # pragma: no cover
        ...

    def is_recurring_line_item(self, line_item):
        return line_item.item_type == self._owned_type


def _item(item_type):
    return SimpleNamespace(item_type=item_type)


def test_default_handler_is_not_recurring():
    """ISP: token-bundle/core handlers inherit the False default."""

    class _Core(_RecurringOwner):
        is_recurring_line_item = ILineItemHandler.is_recurring_line_item

    handler = _Core(LineItemType.TOKEN_BUNDLE)
    assert handler.is_recurring_line_item(_item(LineItemType.TOKEN_BUNDLE)) is False


def test_registry_true_when_any_handler_recurring():
    registry = LineItemHandlerRegistry()
    registry.register(_RecurringOwner(LineItemType.SUBSCRIPTION))
    assert registry.is_recurring_line_item(_item(LineItemType.SUBSCRIPTION)) is True


def test_registry_false_when_no_handler_owns():
    registry = LineItemHandlerRegistry()
    registry.register(_RecurringOwner(LineItemType.SUBSCRIPTION))
    assert registry.is_recurring_line_item(_item(LineItemType.TOKEN_BUNDLE)) is False


def test_determine_session_mode_has_no_subscription_imports():
    from vbwd.plugins import payment_route_helpers

    source = inspect.getsource(payment_route_helpers.determine_session_mode)
    assert "Subscription" not in source
    assert "line_item_registry" in source
    module_source = inspect.getsource(payment_route_helpers)
    assert "from vbwd.models.subscription import" not in module_source
    assert "from vbwd.models.addon_subscription import" not in module_source

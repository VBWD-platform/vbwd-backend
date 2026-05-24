"""Recurring vs one-time line-item dispatch is extensible (Sprint 11 / S1).

Payment plugins must NOT hardcode which line-item types recur. They ask the
line-item registry, so:
  * SUBSCRIPTION (and recurring add-ons) → recurring → the provider sets up a
    repeating charge the user authorised;
  * token bundles / shop items / one-off add-ons → one-time;
  * ANY plugin may register its own line-item type and declare it recurring.
This proves that last point with a custom handler (no subscription plugin).
"""
from types import SimpleNamespace

from vbwd.events.line_item_registry import (
    ILineItemHandler,
    LineItemHandlerRegistry,
    RecurringBillingSpec,
)


def _li(item_type, item_id="x"):
    return SimpleNamespace(item_type=item_type, item_id=item_id, quantity=1)


class _OneTimeHandler(ILineItemHandler):
    """A plugin whose line-item type is a one-off charge (e.g. tokens/shop)."""

    def can_handle_line_item(self, line_item, context):
        return line_item.item_type == "TOKEN_BUNDLE"

    def activate_line_item(self, line_item, context):
        ...

    def reverse_line_item(self, line_item, context):
        ...

    def restore_line_item(self, line_item, context):
        ...

    # inherits is_recurring_line_item → False, recurring_billing_spec → None


class _CustomRecurringHandler(ILineItemHandler):
    """A *custom* plugin introducing its own recurring line-item type."""

    def can_handle_line_item(self, line_item, context):
        return line_item.item_type == "MEMBERSHIP"

    def activate_line_item(self, line_item, context):
        ...

    def reverse_line_item(self, line_item, context):
        ...

    def restore_line_item(self, line_item, context):
        ...

    def is_recurring_line_item(self, line_item):
        return line_item.item_type == "MEMBERSHIP"

    def recurring_billing_spec(self, line_item):
        if line_item.item_type == "MEMBERSHIP":
            return RecurringBillingSpec(name="Gold Membership", billing_period="YEARLY")
        return None


def test_one_time_type_is_not_recurring():
    registry = LineItemHandlerRegistry()
    registry.register(_OneTimeHandler())
    item = _li("TOKEN_BUNDLE")
    assert registry.is_recurring_line_item(item) is False
    assert registry.recurring_billing_spec(item) is None


def test_custom_plugin_can_declare_its_own_recurring_type():
    registry = LineItemHandlerRegistry()
    registry.register(_OneTimeHandler())
    registry.register(_CustomRecurringHandler())

    membership = _li("MEMBERSHIP")
    assert registry.is_recurring_line_item(membership) is True
    spec = registry.recurring_billing_spec(membership)
    assert spec == RecurringBillingSpec(name="Gold Membership", billing_period="YEARLY")

    # An unknown type that no handler owns → one-time.
    assert registry.recurring_billing_spec(_li("SHOP_PRODUCT")) is None


def test_first_matching_handler_supplies_the_spec():
    registry = LineItemHandlerRegistry()
    registry.register(_CustomRecurringHandler())
    registry.register(_OneTimeHandler())
    # Only the custom handler owns MEMBERSHIP; one-time handler ignores it.
    assert registry.recurring_billing_spec(_li("MEMBERSHIP")).name == "Gold Membership"

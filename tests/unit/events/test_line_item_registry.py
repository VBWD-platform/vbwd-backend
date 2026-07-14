"""Unit tests for LineItemHandlerRegistry — TDD-first (Sprint 04a Step 1)."""
from unittest.mock import MagicMock
from uuid import uuid4

from vbwd.events.line_item_registry import (
    ILineItemHandler,
    LineItemContext,
    LineItemHandlerRegistry,
    LineItemResult,
    RecurringBillingSpec,
)


class TestRecurringBillingSpec:
    def test_trial_days_defaults_to_zero(self):
        """Existing callers omit trial_days → provider bills cycle 1 immediately."""
        spec = RecurringBillingSpec(name="Plan", billing_period="MONTHLY")
        assert spec.trial_days == 0

    def test_trial_days_is_carried(self):
        """A free-trial length defers the first recurring charge."""
        spec = RecurringBillingSpec(
            name="Plan", billing_period="MONTHLY", trial_days=14
        )
        assert spec.trial_days == 14


def _make_context(**overrides):
    defaults = {
        "invoice": MagicMock(),
        "user_id": uuid4(),
        "container": MagicMock(),
    }
    defaults.update(overrides)
    return LineItemContext(**defaults)


def _make_handler(
    *, can_handle=True, activate_data=None, reverse_data=None, restore_data=None
):
    """Create a mock handler implementing ILineItemHandler."""
    handler = MagicMock(spec=ILineItemHandler)
    handler.can_handle_line_item.return_value = can_handle
    handler.activate_line_item.return_value = LineItemResult(
        success=True, data=activate_data or {}
    )
    handler.reverse_line_item.return_value = LineItemResult(
        success=True, data=reverse_data or {}
    )
    handler.restore_line_item.return_value = LineItemResult(
        success=True, data=restore_data or {}
    )
    return handler


class TestLineItemHandlerRegistration:
    def test_register_adds_handler(self):
        registry = LineItemHandlerRegistry()
        handler = _make_handler()
        registry.register(handler)
        assert handler in registry.handlers

    def test_register_preserves_order(self):
        registry = LineItemHandlerRegistry()
        handler_a = _make_handler()
        handler_b = _make_handler()
        registry.register(handler_a)
        registry.register(handler_b)
        assert registry.handlers == [handler_a, handler_b]


class TestProcessActivation:
    def test_calls_matching_handler(self):
        registry = LineItemHandlerRegistry()
        handler = _make_handler(
            can_handle=True, activate_data={"subscription_id": "abc"}
        )
        registry.register(handler)

        line_item = MagicMock()
        context = _make_context()
        result = registry.process_activation(line_item, context)

        handler.can_handle_line_item.assert_called_once_with(line_item, context)
        handler.activate_line_item.assert_called_once_with(line_item, context)
        assert result.success is True
        assert result.data == {"subscription_id": "abc"}

    def test_skips_non_matching_handlers(self):
        registry = LineItemHandlerRegistry()
        handler_no = _make_handler(can_handle=False)
        handler_yes = _make_handler(can_handle=True, activate_data={"matched": True})
        registry.register(handler_no)
        registry.register(handler_yes)

        line_item = MagicMock()
        context = _make_context()
        result = registry.process_activation(line_item, context)

        handler_no.activate_line_item.assert_not_called()
        handler_yes.activate_line_item.assert_called_once()
        assert result.data == {"matched": True}

    def test_first_matching_handler_wins(self):
        registry = LineItemHandlerRegistry()
        handler_first = _make_handler(can_handle=True, activate_data={"first": True})
        handler_second = _make_handler(can_handle=True, activate_data={"second": True})
        registry.register(handler_first)
        registry.register(handler_second)

        result = registry.process_activation(MagicMock(), _make_context())

        handler_first.activate_line_item.assert_called_once()
        handler_second.activate_line_item.assert_not_called()
        assert result.data == {"first": True}

    def test_returns_skipped_when_no_handler_matches(self):
        registry = LineItemHandlerRegistry()
        handler = _make_handler(can_handle=False)
        registry.register(handler)

        result = registry.process_activation(MagicMock(), _make_context())

        assert result.skipped is True
        assert result.success is True

    def test_returns_skipped_when_registry_empty(self):
        registry = LineItemHandlerRegistry()
        result = registry.process_activation(MagicMock(), _make_context())
        assert result.skipped is True

    def test_handler_exception_returns_error_result(self):
        registry = LineItemHandlerRegistry()
        handler = _make_handler(can_handle=True)
        handler.activate_line_item.side_effect = RuntimeError("DB exploded")
        registry.register(handler)

        result = registry.process_activation(MagicMock(), _make_context())

        assert result.success is False
        assert "DB exploded" in result.error


class TestProcessReversal:
    def test_delegates_to_matching_handler(self):
        registry = LineItemHandlerRegistry()
        handler = _make_handler(can_handle=True, reverse_data={"cancelled": True})
        registry.register(handler)

        result = registry.process_reversal(MagicMock(), _make_context())

        handler.reverse_line_item.assert_called_once()
        assert result.data == {"cancelled": True}

    def test_returns_skipped_when_no_handler(self):
        registry = LineItemHandlerRegistry()
        result = registry.process_reversal(MagicMock(), _make_context())
        assert result.skipped is True

    def test_handler_exception_returns_error(self):
        registry = LineItemHandlerRegistry()
        handler = _make_handler(can_handle=True)
        handler.reverse_line_item.side_effect = ValueError("bad state")
        registry.register(handler)

        result = registry.process_reversal(MagicMock(), _make_context())

        assert result.success is False
        assert "bad state" in result.error


class TestProcessRestoration:
    def test_delegates_to_matching_handler(self):
        registry = LineItemHandlerRegistry()
        handler = _make_handler(can_handle=True, restore_data={"restored": True})
        registry.register(handler)

        result = registry.process_restoration(MagicMock(), _make_context())

        handler.restore_line_item.assert_called_once()
        assert result.data == {"restored": True}

    def test_returns_skipped_when_no_handler(self):
        registry = LineItemHandlerRegistry()
        result = registry.process_restoration(MagicMock(), _make_context())
        assert result.skipped is True

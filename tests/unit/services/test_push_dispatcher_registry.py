"""S66 — push_dispatcher_registry unit specs.

Generic Kind-1 registry (mirror of checkout_price_adjustment_registry):
plugins register a push handler under their app key; core dispatches an
opaque ``PushEvent`` to every handler, ordered by ascending priority. A
handler exception is logged and never breaks the other handlers (a push
must NEVER fail a message send).
"""
from unittest.mock import MagicMock

import pytest

from vbwd.services.push_dispatcher_registry import (
    PushEvent,
    clear_push_handlers,
    dispatch,
    register_push_handler,
    unregister_push_handler,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_push_handlers()
    yield
    clear_push_handlers()


def _event() -> PushEvent:
    return PushEvent(
        message=MagicMock(),
        conversation=MagicMock(),
        recipient_user_id="recipient-id",
        app="meinchat",
    )


def test_register_and_dispatch_calls_handler_with_event():
    handler = MagicMock()
    register_push_handler("meinchat", handler)
    event = _event()

    dispatch(event)

    handler.assert_called_once_with(event)


def test_unregister_removes_handler():
    handler = MagicMock()
    register_push_handler("meinchat", handler)
    unregister_push_handler("meinchat")

    dispatch(_event())

    handler.assert_not_called()


def test_unregister_unknown_key_is_a_noop():
    unregister_push_handler("never-registered")


def test_handlers_run_in_ascending_priority_order():
    call_order: list = []
    register_push_handler("late", lambda event: call_order.append("late"))
    register_push_handler(
        "early", lambda event: call_order.append("early"), priority=50
    )

    dispatch(_event())

    assert call_order == ["early", "late"]


def test_handler_exception_does_not_break_other_handlers():
    injected_logger = MagicMock()

    def failing_handler(event):
        raise RuntimeError("boom")

    surviving_handler = MagicMock()
    register_push_handler("failing", failing_handler, priority=10)
    register_push_handler("surviving", surviving_handler, priority=20)

    dispatch(_event(), logger=injected_logger)

    surviving_handler.assert_called_once()
    injected_logger.error.assert_called_once()


def test_register_replaces_existing_handler_for_same_key():
    first_handler = MagicMock()
    second_handler = MagicMock()
    register_push_handler("meinchat", first_handler)
    register_push_handler("meinchat", second_handler)

    dispatch(_event())

    first_handler.assert_not_called()
    second_handler.assert_called_once()


def test_push_event_defaults_kind_message_for_back_compat():
    """S68 — existing S66 callers construct a PushEvent without ``kind``;
    it defaults to ``"message"`` and ``originating_device_token`` to None."""
    event = _event()

    assert event.kind == "message"
    assert event.originating_device_token is None


def test_push_event_kind_badge_only_round_trips_through_dispatch():
    """S68 — a ``badge_only`` event reaches the handler unchanged so the
    handler can branch on ``kind`` (no second registry)."""
    handler = MagicMock()
    register_push_handler("meinchat", handler)
    event = PushEvent(
        message=None,
        conversation=MagicMock(),
        recipient_user_id="reader-id",
        app="meinchat",
        kind="badge_only",
        originating_device_token="device-a",
    )

    dispatch(event)

    handler.assert_called_once_with(event)
    delivered = handler.call_args[0][0]
    assert delivered.kind == "badge_only"
    assert delivered.originating_device_token == "device-a"

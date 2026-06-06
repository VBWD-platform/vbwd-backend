"""S50.6 — `receive_events` filters via the frontend-event-type registry.

The route must accept an event type that a plugin registered and reject one that
nobody registered — proving core no longer hardcodes a per-domain whitelist.

The view is exercised directly (decorators unwrapped) so the test stays a pure
unit test: no JWT, no DB, no rate-limiter init.
"""
import json

import pytest
from flask import Flask, g

import vbwd.routes.events as events_module
from vbwd.services.frontend_event_type_registry import (
    clear_frontend_event_types,
    register_frontend_event_types,
)


def _unwrap(view):
    """Peel @require_auth / @limiter.limit (both use functools.wraps)."""
    while hasattr(view, "__wrapped__"):
        view = view.__wrapped__
    return view


class _RecordingDispatcher:
    def __init__(self):
        self.dispatched = []

    def dispatch(self, event):
        self.dispatched.append(event)
        return event


class _Container:
    def __init__(self, dispatcher):
        self._dispatcher = dispatcher

    def event_dispatcher(self):
        return self._dispatcher


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_frontend_event_types()
    yield
    clear_frontend_event_types()


def _call_receive_events(event_type):
    app = Flask(__name__)
    app.config["TESTING"] = True
    dispatcher = _RecordingDispatcher()
    app.container = _Container(dispatcher)  # type: ignore[attr-defined]
    view = _unwrap(events_module.receive_events)

    with app.test_request_context(
        "/api/v1/events",
        method="POST",
        data=json.dumps({"events": [{"type": event_type, "data": {}}]}),
        content_type="application/json",
    ):
        g.user_id = "00000000-0000-0000-0000-000000000001"
        response, status = view()
    return status, response.get_json(), dispatcher


def test_registered_plugin_type_is_accepted():
    register_frontend_event_types({"subscription:created"})

    status, body, dispatcher = _call_receive_events("subscription:created")

    assert status == 200
    assert body["processed"] == 1
    assert body["errors"] is None
    assert len(dispatcher.dispatched) == 1


def test_unregistered_type_is_rejected():
    status, body, dispatcher = _call_receive_events("subscription:created")

    assert status == 200
    assert body["processed"] == 0
    assert body["errors"] == ["Event type 'subscription:created' not allowed"]
    assert dispatcher.dispatched == []


def test_core_base_type_is_always_accepted():
    status, body, dispatcher = _call_receive_events("user:updated")

    assert status == 200
    assert body["processed"] == 1
    assert len(dispatcher.dispatched) == 1

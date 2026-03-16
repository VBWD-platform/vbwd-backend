"""Unit tests for EventContextRegistry."""
import pytest
from plugins.email.src.services.event_context_registry import (
    register,
    get,
    get_all,
    clear,
)

_SCHEMA = {
    "description": "Test event",
    "variables": {
        "user_email": {
            "type": "string",
            "description": "Recipient",
            "example": "a@b.com",
        },
    },
}


@pytest.fixture(autouse=True)
def clean_registry():
    """Each test starts with a clean registry."""
    clear()
    yield
    clear()


class TestRegister:
    def test_register_stores_schema(self):
        register("test.event", _SCHEMA)
        result = get("test.event")
        assert result is not None
        assert result["description"] == "Test event"

    def test_register_updates_existing(self):
        register("ev", _SCHEMA)
        register("ev", {"description": "Updated", "variables": {}})
        assert get("ev")["description"] == "Updated"

    def test_register_multiple_events(self):
        register("a.event", _SCHEMA)
        register("b.event", _SCHEMA)
        assert get("a.event") is not None
        assert get("b.event") is not None


class TestGet:
    def test_get_returns_none_for_unknown(self):
        assert get("not.registered") is None

    def test_get_returns_correct_schema(self):
        register("my.event", _SCHEMA)
        schema = get("my.event")
        assert schema["description"] == "Test event"
        assert "user_email" in schema["variables"]


class TestGetAll:
    def test_get_all_returns_empty_list_when_empty(self):
        assert get_all() == []

    def test_get_all_includes_registered_events(self):
        register("z.event", _SCHEMA)
        register("a.event", _SCHEMA)
        result = get_all()
        assert len(result) == 2
        # Sorted by key
        assert result[0]["event_type"] == "a.event"
        assert result[1]["event_type"] == "z.event"

    def test_get_all_includes_event_type_field(self):
        register("sub.test", _SCHEMA)
        result = get_all()
        assert result[0]["event_type"] == "sub.test"
        assert result[0]["description"] == "Test event"


class TestCoreAutoRegistration:
    def test_importing_event_contexts_registers_core_events(self):
        """event_contexts.py auto-registers 8 core events."""
        import plugins.email.src.services.event_contexts  # noqa: F401

        all_events = [e["event_type"] for e in get_all()]
        assert "subscription.activated" in all_events
        assert "user.registered" in all_events
        assert "user.password_reset" in all_events
        assert len(all_events) >= 8

"""S50.6 — the frontend-event whitelist is a generic, extensible registry.

Core (`vbwd/`) must not hardcode plugin event types (`subscription:*`). It keeps
only generic platform event types (`auth:*`, `user:*`, `payment:*`, `plugin:*`)
and exposes a registry so plugins contribute their own. Core routes the
whitelist check through the registry; it never names a plugin domain.
"""
import pytest

from vbwd.services.frontend_event_type_registry import (
    allowed_frontend_event_types,
    clear_frontend_event_types,
    register_frontend_event_types,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts and ends with a clean plugin-contributed set."""
    clear_frontend_event_types()
    yield
    clear_frontend_event_types()


CORE_BASE_TYPES = {
    "auth:login",
    "auth:logout",
    "auth:token-refreshed",
    "auth:session-expired",
    "user:registered",
    "user:updated",
    "user:deleted",
    "payment:initiated",
    "payment:completed",
    "payment:failed",
    "payment:refunded",
    "plugin:registered",
    "plugin:initialized",
    "plugin:error",
    "plugin:stopped",
}


class TestFrontendEventTypeRegistry:
    def test_base_set_is_the_generic_platform_types(self):
        """With nothing registered, the allowed set is exactly the core base."""
        assert allowed_frontend_event_types() == CORE_BASE_TYPES

    def test_base_set_has_no_subscription_vocabulary(self):
        """Core base must name no plugin domain (no `subscription:*`)."""
        assert not any(
            event_type.startswith("subscription:")
            for event_type in allowed_frontend_event_types()
        )

    def test_registered_types_extend_the_base(self):
        """Plugin-contributed types are unioned with the core base."""
        plugin_types = {"subscription:created", "subscription:cancelled"}
        register_frontend_event_types(plugin_types)

        allowed = allowed_frontend_event_types()
        assert CORE_BASE_TYPES <= allowed
        assert plugin_types <= allowed

    def test_clear_removes_plugin_types_only(self):
        """Clearing drops contributed types but keeps the core base."""
        register_frontend_event_types({"subscription:created"})
        clear_frontend_event_types()

        assert allowed_frontend_event_types() == CORE_BASE_TYPES

    def test_returned_set_is_a_copy(self):
        """Mutating the returned set must not corrupt the registry."""
        allowed = allowed_frontend_event_types()
        allowed.add("attacker:event")

        assert "attacker:event" not in allowed_frontend_event_types()

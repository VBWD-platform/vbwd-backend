"""S09 oracle — plugin-owned repositories must be resolvable from the DI
container after the plugin is enabled.

This catches the 2026-03-27 outage class: subscription extraction
forgot to ``container.subscription_repository = providers.Factory(...)``
in ``on_enable``, and every consumer that tried to resolve through the
container 500'd. Memory: ``project_plugin_di_provider_registration``.

For each plugin in ``PLUGINS_WITH_REPOS``, after the test app boots
(which enables all plugins via ``plugin_manager.load_persisted_state``),
the expected ``<plugin>_<repo>_repository`` provider must be resolvable
on ``app.container``.

The shared helper ``vbwd/plugins/di_helpers.py::register_repositories``
is the canonical way to wire these up — see the docstring there.
"""
import pytest

# (plugin name, expected_provider_attr_on_container, expected_class_name)
EXPECTED_PROVIDERS = [
    # Shop
    ("shop", "shop_product_repository", "ProductRepository"),
    ("shop", "shop_order_repository", "OrderRepository"),
    ("shop", "shop_warehouse_repository", "WarehouseRepository"),
    # Booking
    ("booking", "booking_booking_repository", "BookingRepository"),
    ("booking", "booking_resource_repository", "ResourceRepository"),
    # Meinchat (no ChatRepository — domain uses Conversation / Message /
    # Contact / Nickname / TokenTransfer repos)
    ("meinchat", "meinchat_conversation_repository", "ConversationRepository"),
    ("meinchat", "meinchat_message_repository", "MessageRepository"),
]


# ── di_helpers contract ────────────────────────────────────────────────────


class _SessionTakingRepo:
    """Tiny class with a ``session`` kwarg so the Factory invocation works."""

    def __init__(self, session) -> None:
        self.session = session


def test_register_repositories_attaches_factory_per_entry():
    """Helper must setattr a ``providers.Factory(cls, session=db_session)``
    for each entry in the mapping."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from vbwd.plugins.di_helpers import register_repositories

    sentinel_session = MagicMock()
    fake_container = SimpleNamespace(db_session=sentinel_session)

    register_repositories(fake_container, {"sentinel_repository": _SessionTakingRepo})

    assert hasattr(fake_container, "sentinel_repository")
    instance = fake_container.sentinel_repository()
    assert isinstance(instance, _SessionTakingRepo)
    assert instance.session is sentinel_session


def test_unregister_repositories_removes_attrs_and_is_idempotent():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from vbwd.plugins.di_helpers import (
        register_repositories,
        unregister_repositories,
    )

    fake_container = SimpleNamespace(db_session=MagicMock())
    register_repositories(fake_container, {"sentinel_repository": _SessionTakingRepo})

    unregister_repositories(fake_container, ["sentinel_repository"])
    assert not hasattr(fake_container, "sentinel_repository")

    # Idempotent — second call on a missing attr is a no-op.
    unregister_repositories(fake_container, ["sentinel_repository"])


# ── Per-plugin: the audit-flagged trio (shop / booking / meinchat) ──────────


@pytest.mark.parametrize(
    "plugin_name, provider_attr, expected_class_name",
    EXPECTED_PROVIDERS,
    ids=[f"{p}::{a}" for p, a, _ in EXPECTED_PROVIDERS],
)
def test_plugin_repos_resolvable_from_container_after_enable(
    app, plugin_name, provider_attr, expected_class_name
):
    """The expected provider exists on app.container and resolves to an
    instance of the named class."""
    container = app.container

    assert hasattr(container, provider_attr), (
        f"Plugin '{plugin_name}' did not register "
        f"`container.{provider_attr}` in on_enable. Use "
        f"`vbwd.plugins.di_helpers.register_repositories(container, ...)` — "
        "see the subscription plugin for the reference pattern."
    )

    factory = getattr(container, provider_attr)
    instance = factory()
    assert type(instance).__name__ == expected_class_name, (
        f"container.{provider_attr} resolved to {type(instance).__name__!r} "
        f"but expected {expected_class_name!r}."
    )

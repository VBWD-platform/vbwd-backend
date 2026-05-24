"""Agnosticism fence — core ships no orphan subscription code.

Sprint 01 (Phase 0) deleted the unreachable subscription route modules and
the unregistered subscription handler modules that the 2026-03-27 extraction
was supposed to remove but never did. These assertions keep them gone: the
subscription feature is owned by the `subscription` plugin, not core.
"""
import importlib.util

import vbwd.handlers


ORPHAN_ROUTE_MODULES = [
    "vbwd.routes.subscriptions",
    "vbwd.routes.tarif_plans",
    "vbwd.routes.addons",
    "vbwd.routes.admin.subscriptions",
    "vbwd.routes.admin.plans",
    "vbwd.routes.admin.addons",
    "vbwd.routes.admin.categories",
    "vbwd.routes.admin.analytics",
]

ORPHAN_HANDLER_MODULES = [
    "vbwd.handlers.checkout_handler",
    "vbwd.handlers.subscription_handlers",
    "vbwd.handlers.subscription_cancel_handler",
]

# Blueprint names the deleted core route modules used. The subscription
# plugin registers its own blueprint under a different name, so a core app
# must never expose any of these.
ORPHAN_BLUEPRINT_NAMES = [
    "subscriptions",
    "tarif_plans",
    "addons",
    "admin_subs",
    "admin_plans",
    "admin_addons",
    "admin_categories",
    "admin_analytics",
]


def test_core_handlers_init_has_no_checkout_handler():
    """`vbwd.handlers` must not re-export the dead core CheckoutHandler.

    The live CheckoutHandler is the subscription plugin's own.
    """
    assert not hasattr(vbwd.handlers, "CheckoutHandler")
    assert "CheckoutHandler" not in getattr(vbwd.handlers, "__all__", [])


def test_orphan_subscription_route_modules_absent():
    for module_path in ORPHAN_ROUTE_MODULES:
        assert (
            importlib.util.find_spec(module_path) is None
        ), f"{module_path} should have been deleted (owned by the plugin)"


def test_orphan_subscription_handler_modules_absent():
    for module_path in ORPHAN_HANDLER_MODULES:
        assert (
            importlib.util.find_spec(module_path) is None
        ), f"{module_path} should have been deleted (owned by the plugin)"


def test_app_registers_no_core_subscription_blueprint(app):
    registered = set(app.blueprints)
    leaked = registered.intersection(ORPHAN_BLUEPRINT_NAMES)
    assert not leaked, f"core registered orphan subscription blueprints: {leaked}"

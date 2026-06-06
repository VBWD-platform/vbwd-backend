"""Sprint 09/11 — backend agnosticism oracle (the extraction's exit gate).

Aggregates the per-slice guards into one authoritative contract: core owns NO
subscription routes / repositories / services / DI / feature-gating / line-item
coupling / seeder imports, **and no subscription model classes** (Sprint 11
supersedes decision A — the 5 model classes now live in the subscription
plugin, and the core invoice carries no subscription/plan FK). Per (A1) the
plugin owns its Alembic migration branch.

If any assertion here goes red, the subscription extraction has regressed.
"""
import importlib.util
import inspect
import os

import pytest


# The 5 model classes that left core for the subscription plugin (Sprint 11).
MOVED_MODEL_MODULES = [
    "vbwd.models.subscription",
    "vbwd.models.tarif_plan",
    "vbwd.models.tarif_plan_category",
    "vbwd.models.addon",
    "vbwd.models.addon_subscription",
]

# Peer plugins that must reach subscription data via ports/registries, never by
# importing the (now plugin-owned) model classes from the old core path.
PEER_PLUGIN_DIRS = ["stripe", "paypal", "yookassa", "taro", "analytics", "ghrm"]


# ── Modules core must NOT contain (deleted in S1/S4) ─────────────────────────
DELETED_CORE_MODULES = [
    # Orphan routes (S1)
    "vbwd.routes.subscriptions",
    "vbwd.routes.tarif_plans",
    "vbwd.routes.addons",
    "vbwd.routes.admin.subscriptions",
    "vbwd.routes.admin.plans",
    "vbwd.routes.admin.addons",
    "vbwd.routes.admin.categories",
    # Unregistered handlers (S1)
    "vbwd.handlers.checkout_handler",
    "vbwd.handlers.subscription_handlers",
    "vbwd.handlers.subscription_cancel_handler",
    # Repos + services (S4)
    "vbwd.repositories.subscription_repository",
    "vbwd.repositories.tarif_plan_repository",
    "vbwd.repositories.tarif_plan_category_repository",
    "vbwd.repositories.addon_repository",
    "vbwd.repositories.addon_subscription_repository",
    "vbwd.services.subscription_service",
    "vbwd.services.tarif_plan_service",
    "vbwd.services.tarif_plan_category_service",
    # Feature gating (S3)
    "vbwd.services.feature_guard",
    # Subscription read-model port → generic invoice extra-fields registry (S50.3)
    "vbwd.services.subscription_read_model",
]


@pytest.mark.parametrize("module_path", DELETED_CORE_MODULES)
def test_core_does_not_contain_subscription_module(module_path):
    assert (
        importlib.util.find_spec(module_path) is None
    ), f"{module_path} must not exist in core (owned by the subscription plugin)"


def test_core_repositories_and_services_export_no_subscription():
    import vbwd.repositories as repos
    import vbwd.services as services

    for name in (
        "SubscriptionRepository",
        "TarifPlanRepository",
        "AddOnRepository",
        "AddOnSubscriptionRepository",
    ):
        assert not hasattr(repos, name), f"core repositories still exports {name}"
    for name in ("SubscriptionService", "TarifPlanService"):
        assert not hasattr(services, name), f"core services still exports {name}"


def test_core_container_has_no_subscription_factories():
    from vbwd.container import Container

    for name in (
        "subscription_repository",
        "tarif_plan_repository",
        "tarif_plan_category_repository",
        "addon_repository",
        "addon_subscription_repository",
        "feature_guard",
    ):
        assert not hasattr(Container, name), f"core container still wires {name}"


def test_core_user_blueprint_serves_no_checkout_or_addons(app):
    """/checkout + user /addons are plugin-owned (S2). Core `user` blueprint
    must own none."""
    for rule in app.url_map.iter_rules():
        if rule.endpoint.startswith("user."):
            path = str(rule)
            assert "/checkout" not in path, f"core user_bp serves {path}"
            assert "/addons" not in path, f"core user_bp serves {path}"


def test_core_invoice_line_item_has_no_subscription_coupling():
    """Catalog-id resolution delegates to the line-item registry (S1)."""
    from vbwd.models.invoice_line_item import InvoiceLineItem

    source = inspect.getsource(InvoiceLineItem._resolve_catalog_item_id)
    assert "Subscription" not in source
    assert "line_item_registry" in source


def test_core_payment_route_helpers_has_no_subscription_import():
    """Recurrence resolution delegates to the line-item registry (S5a)."""
    from vbwd.plugins import payment_route_helpers

    source = inspect.getsource(payment_route_helpers)
    assert "from vbwd.models.subscription import" not in source
    assert "from vbwd.models.addon_subscription import" not in source


def test_core_seeders_do_not_import_subscription_models():
    """Subscription demo/test data is plugin-contributed via the demo-data
    registry (S5b)."""
    from vbwd.cli import _demo_seeder
    from vbwd.testing import test_data_seeder

    for module in (_demo_seeder, test_data_seeder):
        source = inspect.getsource(module)
        assert "from vbwd.models.tarif_plan import" not in source
        assert "from vbwd.models.subscription import" not in source
        assert "from vbwd.models.addon import" not in source


def test_core_deletion_info_is_generic():
    """S6 — core deletion-info reports a generic dependencies[] via the
    registry; it names no subscription domain."""
    from vbwd.routes.admin import users as users_routes

    source = inspect.getsource(users_routes.get_deletion_info)
    assert "resolve_deletion_dependencies" in source
    assert "subscription_count" not in source


def test_core_admin_invoice_detail_uses_generic_extra_fields_registry():
    """S50.3 — admin invoice detail merges plugin extra fields via the generic
    registry; it names no subscription read-model symbol."""
    from vbwd.routes.admin import invoices as invoices_routes

    source = inspect.getsource(invoices_routes.get_invoice)
    assert "aggregate_invoice_extra_fields" in source
    assert "subscription_read_model" not in source


def test_core_admin_user_routes_name_no_subscription_read_model():
    """S50.3 — the subscription read-model port is gone from core user routes;
    the deleted /addons route is now a subscription-plugin endpoint."""
    from vbwd.routes.admin import users as users_routes

    source = inspect.getsource(users_routes)
    assert "subscription_read_model" not in source
    assert not hasattr(users_routes, "get_user_addons")


def test_core_has_generic_subscription_ports():
    """Core exposes the generic ports the plugin implements (S3/S4).

    The subscription read model is no longer a core port (S50.3): invoice
    enrichment now flows through the generic invoice extra-fields registry.
    """
    from vbwd.services.entitlement import IEntitlementProvider  # noqa: F401
    from vbwd.services.invoice_extra_fields_registry import (  # noqa: F401
        register_invoice_extra_fields_provider,
    )
    from vbwd.services.demo_data_registry import (  # noqa: F401
        register_catalog_seeder,
    )


def test_subscription_plugin_owns_a_migration_branch():
    """Decision A1 — plugin owns its Alembic migration branch."""
    import os

    here = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    alembic_ini = os.path.join(here, "alembic.ini")
    with open(alembic_ini, encoding="utf-8") as handle:
        content = handle.read()
    assert "plugins/subscription/migrations/versions" in content


def test_core_has_no_subscription_email_templates_or_methods():
    """S5 — subscription/payment email templates + methods are plugin-owned."""
    import os
    from vbwd.services.email_service import EmailService

    here = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    core_email = os.path.join(here, "vbwd", "templates", "email")
    present = set(os.listdir(core_email)) if os.path.isdir(core_email) else set()
    for tmpl in (
        "subscription_activated.html",
        "subscription_cancelled.html",
        "payment_receipt.html",
        "payment_failed.html",
        "renewal_reminder.html",
    ):
        assert tmpl not in present, f"core still ships email template {tmpl}"
    for method in (
        "send_subscription_activated",
        "send_subscription_cancelled",
        "send_payment_receipt",
        "send_payment_failed",
    ):
        assert not hasattr(EmailService, method)
    assert hasattr(EmailService, "register_template_path")


@pytest.mark.parametrize("module_path", MOVED_MODEL_MODULES)
def test_subscription_model_modules_left_core(module_path):
    """Sprint 11 (supersedes A) — the 5 model classes now live in the
    subscription plugin; their old core modules are gone."""
    assert (
        importlib.util.find_spec(module_path) is None
    ), f"{module_path} must not exist in core (owned by the subscription plugin)"


def test_core_models_init_exports_none_of_the_five():
    import vbwd.models as models

    for name in (
        "Subscription",
        "TarifPlan",
        "TarifPlanCategory",
        "AddOn",
        "AddOnSubscription",
        "addon_tarif_plans",
        "tarif_plan_category_plans",
    ):
        assert not hasattr(models, name), f"core vbwd.models still exports {name}"


def test_core_invoice_has_no_subscription_or_plan_fk():
    """S4 — the subscription↔invoice link is the SUBSCRIPTION line item, not a
    core column."""
    from vbwd.models.invoice import UserInvoice

    columns = {column.name for column in UserInvoice.__table__.columns}
    assert "subscription_id" not in columns
    assert "tarif_plan_id" not in columns


def test_peer_plugins_do_not_import_core_subscription_models():
    """The payment + read-model peers reach subscription data via ports, never
    by importing the moved model classes from the old `vbwd.models.*` path."""
    plugins_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    plugins_root = os.path.join(plugins_root, "plugins")
    forbidden = tuple(MOVED_MODEL_MODULES)
    offenders = []
    for plugin in PEER_PLUGIN_DIRS:
        plugin_dir = os.path.join(plugins_root, plugin)
        for dirpath, _dirs, files in os.walk(plugin_dir):
            if "__pycache__" in dirpath:
                continue
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                with open(path, encoding="utf-8") as handle:
                    source = handle.read()
                for module_path in forbidden:
                    if module_path in source:
                        offenders.append(f"{plugin}: {filename} -> {module_path}")
    assert not offenders, "peer plugins import core subscription models:\n" + "\n".join(
        offenders
    )

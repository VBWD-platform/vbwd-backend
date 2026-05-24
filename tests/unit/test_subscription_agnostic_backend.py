"""Sprint 09 — backend agnosticism oracle (the extraction's exit gate).

Aggregates the per-slice guards (S1–S8) into one authoritative contract:
core owns NO subscription routes / repositories / services / DI /
feature-gating / line-item coupling / seeder imports. Per decision (A) the
subscription model *classes* remain core-defined (shared domain — 6 plugins
depend on them); per (A1) the plugin owns its Alembic migration branch.

If any assertion here goes red, the subscription extraction has regressed.
"""
import importlib.util
import inspect

import pytest


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


def test_core_has_generic_subscription_ports():
    """Core exposes the generic ports the plugin implements (S3/S4)."""
    from vbwd.services.entitlement import IEntitlementProvider  # noqa: F401
    from vbwd.services.subscription_read_model import (  # noqa: F401
        ISubscriptionReadModel,
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


def test_subscription_models_stay_in_core_per_decision_A():
    """Decision A — the 5 model classes remain core-defined (shared domain;
    6 plugins depend on them). This is an intentional deviation from a full
    leaf extraction, recorded in reports/02 R3."""
    from vbwd.models.subscription import Subscription  # noqa: F401
    from vbwd.models.tarif_plan import TarifPlan  # noqa: F401

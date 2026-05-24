"""S4 — core subscription repos/services gone; read port replaces them.

Core admin surfaces (invoice detail, user deletion-info/delete, user
addons) get subscription data only through the generic read port. With no
provider registered the null default yields empty enrichment (locked
decision), and the core repo/service modules no longer exist.
"""
import importlib.util

import pytest

from vbwd.services.subscription_read_model import (
    ISubscriptionReadModel,
    register_subscription_read_model,
    clear_subscription_read_model,
    resolve_subscription_read_model,
)

DELETED_CORE_MODULES = [
    "vbwd.repositories.subscription_repository",
    "vbwd.repositories.tarif_plan_repository",
    "vbwd.repositories.tarif_plan_category_repository",
    "vbwd.repositories.addon_repository",
    "vbwd.repositories.addon_subscription_repository",
    "vbwd.services.subscription_service",
    "vbwd.services.tarif_plan_service",
    "vbwd.services.tarif_plan_category_service",
]


@pytest.fixture(autouse=True)
def _reset():
    clear_subscription_read_model()
    yield
    clear_subscription_read_model()


@pytest.mark.parametrize("module_path", DELETED_CORE_MODULES)
def test_core_subscription_repo_service_modules_are_gone(module_path):
    assert importlib.util.find_spec(module_path) is None


def test_core_repositories_init_does_not_export_subscription():
    import vbwd.repositories as repos

    for name in (
        "SubscriptionRepository",
        "TarifPlanRepository",
        "AddOnRepository",
        "AddOnSubscriptionRepository",
    ):
        assert not hasattr(repos, name)


def test_core_services_init_does_not_export_subscription():
    import vbwd.services as services

    for name in ("SubscriptionService", "TarifPlanService"):
        assert not hasattr(services, name)


def test_core_container_has_no_subscription_factories():
    from vbwd.container import Container

    for name in (
        "subscription_repository",
        "tarif_plan_repository",
        "tarif_plan_category_repository",
        "addon_repository",
        "addon_subscription_repository",
    ):
        assert not hasattr(Container, name)


def test_null_read_model_is_empty_when_no_provider():
    rm = resolve_subscription_read_model()
    assert rm.enrich_invoice(object()) == {}
    assert rm.count_user_subscriptions("u") == 0
    assert rm.user_addon_subscriptions("u") == []


def test_registered_read_model_takes_precedence():
    class _RM(ISubscriptionReadModel):
        def enrich_invoice(self, invoice):
            return {"plan_name": "Pro"}

        def count_user_subscriptions(self, user_id):
            return 3

        def user_addon_subscriptions(self, user_id):
            return [{"id": "a"}]

    register_subscription_read_model(_RM())
    rm = resolve_subscription_read_model()
    assert rm.enrich_invoice(object()) == {"plan_name": "Pro"}
    assert rm.count_user_subscriptions("u") == 3
    assert rm.user_addon_subscriptions("u") == [{"id": "a"}]

"""S4 — core subscription repos/services gone.

Core admin surfaces (invoice detail, user deletion-info/delete) get
subscription data only through generic, domain-neutral registries (the
invoice extra-fields registry and the deletion-dependency registry); the
core subscription repo/service modules no longer exist.
"""
import importlib.util

import pytest

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

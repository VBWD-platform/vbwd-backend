"""S17 — catalog_read_model port contract tests."""
from unittest.mock import MagicMock

import pytest

from vbwd.services.catalog_read_model import (
    ICatalogReadModel,
    clear_catalog_read_model,
    register_catalog_read_model,
    resolve_catalog_read_model,
)


@pytest.fixture(autouse=True)
def _isolate():
    clear_catalog_read_model()
    yield
    clear_catalog_read_model()


class _FakeCatalogReadModel(ICatalogReadModel):
    def category_labels_by_slugs(self, slugs):
        return {slug: f"Label-{slug}" for slug in slugs}

    def plan_ids_in_category(self, category_slug):
        return []


def test_null_default_returns_empty_labels():
    """Disabled-plugin path: empty mapping for any requested slugs."""
    read_model = resolve_catalog_read_model()
    assert read_model.category_labels_by_slugs(["any", "slug"]) == {}


def test_null_default_returns_empty_plan_ids():
    read_model = resolve_catalog_read_model()
    assert read_model.plan_ids_in_category("any-category") == []


def test_register_then_resolve():
    fake = _FakeCatalogReadModel()
    register_catalog_read_model(fake)
    assert resolve_catalog_read_model() is fake


def test_clear_returns_to_null_default():
    register_catalog_read_model(_FakeCatalogReadModel())
    clear_catalog_read_model()
    assert resolve_catalog_read_model().category_labels_by_slugs(["x"]) == {}


def test_double_register_replaces_previous():
    register_catalog_read_model(_FakeCatalogReadModel())
    second = MagicMock(spec=ICatalogReadModel)
    register_catalog_read_model(second)
    assert resolve_catalog_read_model() is second

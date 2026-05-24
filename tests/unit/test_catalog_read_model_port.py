"""Guards for the generic plan-catalog read port (core stays agnostic)."""
from uuid import uuid4

from vbwd.services.catalog_read_model import (
    ICatalogReadModel,
    resolve_catalog_read_model,
    register_catalog_read_model,
    clear_catalog_read_model,
)


def test_null_default_is_empty():
    """No plugin → empty catalog (ghrm shows no categories / no plan filter)."""
    clear_catalog_read_model()
    rm = resolve_catalog_read_model()
    assert rm.category_labels_by_slugs(["x"]) == {}
    assert rm.plan_ids_in_category("x") == []


def test_registered_read_model_supplies_catalog():
    pid = uuid4()

    class _Fake(ICatalogReadModel):
        def category_labels_by_slugs(self, slugs):
            return {s: s.title() for s in slugs}

        def plan_ids_in_category(self, category_slug):
            return [pid] if category_slug == "backend" else []

    try:
        register_catalog_read_model(_Fake())
        rm = resolve_catalog_read_model()
        assert rm.category_labels_by_slugs(["a", "b"]) == {"a": "A", "b": "B"}
        assert rm.plan_ids_in_category("backend") == [pid]
        assert rm.plan_ids_in_category("nope") == []
    finally:
        clear_catalog_read_model()

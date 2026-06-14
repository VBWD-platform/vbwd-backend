"""S85.1a — the dead persisted ``Price`` model + ``vbwd_price`` table are gone.

S85.0 introduced the computed ``Price`` value object (``vbwd/pricing/price.py``).
This sub-sprint removes the OLD persisted ``Price`` ORM model so there is exactly
one ``Price`` in the codebase. The persisted model was dead — nothing read a
``vbwd_price`` row at runtime (only the demo/ghrm seeders wrote one, and even
``TarifPlan`` carried its own legacy ``price``/``currency`` alongside the FK).

These are characterisation tests for the teardown:
- the persisted model module is gone;
- ``vbwd.models`` no longer exports a ``Price`` symbol;
- the ONLY surviving ``Price`` import path is the computed value object.
"""
import importlib

import pytest


def test_persisted_price_module_is_deleted():
    """``from vbwd.models.price import Price`` must fail — module removed."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("vbwd.models.price")


def test_models_package_no_longer_exports_price():
    """``vbwd.models`` must not re-export the persisted ``Price`` model."""
    import vbwd.models as models_package

    assert not hasattr(models_package, "Price"), (
        "vbwd.models still exports a persisted Price model; the dead "
        "vbwd_price model must be removed (S85.1a)."
    )


def test_only_price_is_the_computed_value_object():
    """The single remaining ``Price`` is the computed value object (S85.0)."""
    from vbwd.pricing.price import Price as ComputedPrice

    # The value object is a frozen dataclass with netto/brutto/taxes/currency,
    # not a SQLAlchemy model bound to a table.
    assert not hasattr(ComputedPrice, "__tablename__")

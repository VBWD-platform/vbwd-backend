"""Guard: the orphan ``UserCase`` model is fully removed (S94 Slice 2).

``UserCase`` / ``UserCaseStatus`` were never wired (zero routes/services); this
test fails if either is reintroduced into the public model surface or the
``User`` ORM relationship.
"""
import importlib

import vbwd.models as models
from vbwd.models.user import User


def test_user_case_module_is_gone():
    assert importlib.util.find_spec("vbwd.models.user_case") is None


def test_models_package_no_longer_exposes_user_case():
    assert not hasattr(models, "UserCase")
    assert not hasattr(models, "UserCaseStatus")
    assert "UserCase" not in models.__all__
    assert "UserCaseStatus" not in models.__all__


def test_user_has_no_cases_relationship():
    assert "cases" not in User.__mapper__.relationships

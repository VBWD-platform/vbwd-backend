"""S77 — CustomFieldService value validation (unit, MagicMock repos).

Values are validated against the def's ``type`` / ``options`` on write:
text->str, number->int/float, bool->bool, date->ISO date, select->value in
options, multiselect->list subset of options. Bad value/type raises
``CustomFieldValidationError``.
"""
from unittest.mock import MagicMock

import pytest

from vbwd.models.custom_field_def import CustomFieldDef
from vbwd.services.custom_field_service import CustomFieldService
from vbwd.services.tags_and_custom_fields import CustomFieldValidationError


def _def(field_type, options=None):
    definition = CustomFieldDef(
        entity_type="user",
        key="field",
        label="Field",
        type=field_type,
        options=options,
        sort_order=0,
        is_active=True,
    )
    return definition


def _service():
    def_repo = MagicMock()
    value_repo = MagicMock()
    return CustomFieldService(def_repo=def_repo, value_repo=value_repo), def_repo


@pytest.mark.parametrize(
    "field_type,options,good,bad",
    [
        ("text", None, "hello", 123),
        ("number", None, 42, "not-a-number"),
        ("number", None, 3.14, True),  # bool is not a number
        ("bool", None, True, "yes"),
        ("date", None, "2026-06-13", "13/06/2026"),
        ("select", ["a", "b"], "a", "c"),
        ("multiselect", ["a", "b"], ["a", "b"], ["a", "x"]),
        ("multiselect", ["a", "b"], [], "a"),  # value must be a list
    ],
)
def test_validate_value_accepts_good_rejects_bad(field_type, options, good, bad):
    service, _ = _service()
    definition = _def(field_type, options)

    service.validate_value(definition, good)  # must not raise

    with pytest.raises(CustomFieldValidationError):
        service.validate_value(definition, bad)


def test_none_is_always_valid_it_clears():
    service, _ = _service()
    service.validate_value(_def("number"), None)  # must not raise

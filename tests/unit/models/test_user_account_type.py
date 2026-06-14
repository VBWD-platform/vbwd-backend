"""S74 — UserDetails.account_type model + validation unit tests."""
import pytest

from vbwd.models.enums import AccountType
from vbwd.models.user_details import (
    AccountTypeValidationError,
    UserDetails,
    validate_account_type,
)


def test_account_type_allowed_values():
    assert AccountType.values() == ("private", "business")


def test_to_dict_includes_account_type():
    details = UserDetails()
    details.account_type = "business"
    details.company = "Acme Corp"
    result = details.to_dict()
    assert result["account_type"] == "business"


def test_to_dict_defaults_account_type_to_private_when_unset():
    details = UserDetails()
    # No DB default applied in-memory; to_dict() falls back to private.
    result = details.to_dict()
    assert result["account_type"] == "private"


def test_validate_none_account_type_is_noop():
    # None means "field untouched" — never raises.
    validate_account_type(None, None)


def test_validate_unknown_account_type_raises():
    with pytest.raises(AccountTypeValidationError, match="Invalid account type"):
        validate_account_type("enterprise", "Acme Corp")


def test_validate_business_without_company_raises():
    with pytest.raises(AccountTypeValidationError, match="Company is required"):
        validate_account_type("business", None)


def test_validate_business_with_blank_company_raises():
    with pytest.raises(AccountTypeValidationError, match="Company is required"):
        validate_account_type("business", "   ")


def test_validate_business_with_company_passes():
    validate_account_type("business", "Acme Corp")


def test_validate_private_without_company_passes():
    validate_account_type("private", None)

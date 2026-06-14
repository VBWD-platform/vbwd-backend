"""S74 — invoice billing party renders by account type."""
from types import SimpleNamespace

from vbwd.routes.invoices import _build_customer_party


def _user(account_type, **detail_overrides):
    details = SimpleNamespace(
        first_name="Ada",
        last_name="Lovelace",
        company="Acme Corp",
        tax_number="DE123456789",
        phone="+49 30 0000",
        address="Some Street 1",
        account_type=account_type,
        **detail_overrides,
    )
    return SimpleNamespace(email="ada@example.com", details=details)


def test_business_party_uses_company_and_vat():
    party = _build_customer_party(_user("business"))
    assert party["name"] == "Acme Corp"
    assert party["tax_number"] == "DE123456789"


def test_private_party_uses_person_name_and_hides_vat():
    party = _build_customer_party(_user("private"))
    assert party["name"] == "Ada Lovelace"
    assert party["tax_number"] == ""


def test_missing_details_defaults_to_private_empty_name():
    user = SimpleNamespace(email="x@example.com", details=None)
    party = _build_customer_party(user)
    assert party["name"] == ""
    assert party["email"] == "x@example.com"
    assert party["tax_number"] == ""

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
    # No details → empty address, no crash.
    assert party["address"] == ""


def test_party_address_uses_real_full_address_with_state():
    from vbwd.models.user import User
    from vbwd.models.user_details import UserDetails

    details = UserDetails()
    details.first_name = "Ada"
    details.last_name = "Lovelace"
    details.address_line_1 = "1 Analytical Way"
    details.city = "Munich"
    details.state = "Bavaria"
    details.postal_code = "80331"
    details.country = "DE"
    user = User()
    user.email = "ada@example.com"
    user.details = details

    party = _build_customer_party(user)
    assert party["address"] != ""
    assert "Bavaria" in party["address"]
    assert "80331" in party["address"]

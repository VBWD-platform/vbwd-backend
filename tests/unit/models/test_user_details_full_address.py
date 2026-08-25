"""UserDetails.full_address includes state and skips empty lines."""
from vbwd.models.user_details import UserDetails


def _details(**overrides):
    details = UserDetails()
    details.address_line_1 = overrides.get("address_line_1", "1 Analytical Way")
    details.address_line_2 = overrides.get("address_line_2", None)
    details.city = overrides.get("city", "Munich")
    details.state = overrides.get("state", "Bavaria")
    details.postal_code = overrides.get("postal_code", "80331")
    details.country = overrides.get("country", "DE")
    return details


def test_full_address_includes_state():
    address = _details().full_address
    assert "Bavaria" in address
    # State is rendered after the postal/city line and before country.
    lines = address.split("\n")
    assert lines.index("Bavaria") == lines.index("80331 Munich") + 1
    assert lines.index("Bavaria") < lines.index("DE")


def test_full_address_skips_empty_state():
    address = _details(state=None).full_address
    assert "Bavaria" not in address
    # Empty state line is omitted entirely — no blank line left behind.
    assert "\n\n" not in address
    assert address.split("\n") == ["1 Analytical Way", "80331 Munich", "DE"]

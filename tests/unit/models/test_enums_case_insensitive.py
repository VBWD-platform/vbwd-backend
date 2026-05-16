"""Case-insensitive parsing for user-facing enums.

Regression coverage for the "Invalid status: active" bug: the admin
frontend sends lowercase ``status`` while the enum values are uppercase.
``UserStatus``/``UserRole`` must accept any casing at the parse boundary
while keeping their canonical UPPERCASE values (DB column + JSON
contract) and ``enum.Enum`` identity semantics (Liskov).
"""
import pytest

from vbwd.models.enums import UserRole, UserStatus


@pytest.mark.parametrize(
    "raw_value,expected_member",
    [
        ("active", UserStatus.ACTIVE),
        ("ACTIVE", UserStatus.ACTIVE),
        ("Active", UserStatus.ACTIVE),
        ("  active  ", UserStatus.ACTIVE),
        ("pending", UserStatus.PENDING),
        ("suspended", UserStatus.SUSPENDED),
        ("deleted", UserStatus.DELETED),
    ],
)
def test_user_status_accepts_any_casing(raw_value, expected_member):
    """Lookup is case-insensitive and identity-preserving."""
    assert UserStatus(raw_value) is expected_member


@pytest.mark.parametrize(
    "raw_value,expected_member",
    [
        ("admin", UserRole.ADMIN),
        ("ADMIN", UserRole.ADMIN),
        ("Admin", UserRole.ADMIN),
        ("user", UserRole.USER),
        ("super_admin", UserRole.SUPER_ADMIN),
        ("vendor", UserRole.VENDOR),
    ],
)
def test_user_role_accepts_any_casing(raw_value, expected_member):
    """Lookup is case-insensitive and identity-preserving."""
    assert UserRole(raw_value) is expected_member


def test_unknown_value_still_raises_value_error():
    """Unknown strings keep raising ValueError (error contract intact)."""
    with pytest.raises(ValueError):
        UserStatus("not-a-status")
    with pytest.raises(ValueError):
        UserRole("not-a-role")


def test_canonical_value_unchanged_for_db_and_json():
    """Persisted/serialized value stays UPPERCASE — no schema drift."""
    assert UserStatus.ACTIVE.value == "ACTIVE"
    assert UserRole.SUPER_ADMIN.value == "SUPER_ADMIN"


def test_passing_member_through_is_idempotent():
    """Cls(member) returns the same member (Liskov substitute)."""
    assert UserStatus(UserStatus.ACTIVE) is UserStatus.ACTIVE
    assert UserRole(UserRole.ADMIN) is UserRole.ADMIN


def test_membership_and_iteration_unaffected():
    """Coercion adds no phantom members."""
    assert len(list(UserStatus)) == 4
    assert UserStatus.ACTIVE in list(UserStatus)

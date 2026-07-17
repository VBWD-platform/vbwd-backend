"""S23 — UserService.admin_update unit tests.

Covers the validation paths the route used to handle inline. Each test
constructs a UserService with mocked repos + a mocked session.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.services.user_service import (
    AdminUserUpdateError,
    UserService,
)


@pytest.fixture
def details_stub():
    return SimpleNamespace(
        first_name=None,
        last_name=None,
        phone=None,
        address_line_1=None,
    )


@pytest.fixture
def user_stub(details_stub):
    user = MagicMock()
    user.id = "user-1"
    user.status = UserStatus.ACTIVE
    user.role = UserRole.USER
    user.details = details_stub
    return user


@pytest.fixture
def user_repo(user_stub):
    repo = MagicMock()
    repo.find_by_id.return_value = user_stub
    repo.save.side_effect = lambda u: u
    return repo


@pytest.fixture
def details_repo():
    return MagicMock()


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def token_service():
    """S138.0: the admin token-balance set is a delta through TokenService."""
    service = MagicMock()
    service.get_balance.return_value = 0
    return service


@pytest.fixture
def service(user_repo, details_repo, token_service):
    return UserService(
        user_repository=user_repo,
        user_details_repository=details_repo,
        token_service=token_service,
    )


def test_returns_none_when_user_missing(service, user_repo, session):
    user_repo.find_by_id.return_value = None
    assert service.admin_update("missing", {"status": "active"}, session) is None


def test_is_active_true_sets_active_status(service, user_stub, session):
    service.admin_update("user-1", {"is_active": True}, session)
    assert user_stub.status == UserStatus.ACTIVE


def test_is_active_false_sets_suspended_status(service, user_stub, session):
    service.admin_update("user-1", {"is_active": False}, session)
    assert user_stub.status == UserStatus.SUSPENDED


def test_invalid_status_raises_with_field_name(service, session):
    with pytest.raises(AdminUserUpdateError, match="Invalid status"):
        service.admin_update("user-1", {"status": "not-a-status"}, session)


def test_invalid_role_raises(service, session):
    with pytest.raises(AdminUserUpdateError, match="Invalid role"):
        service.admin_update("user-1", {"role": "imaginary-role"}, session)


def test_short_password_raises(service, session):
    with pytest.raises(AdminUserUpdateError, match="at least 8"):
        service.admin_update("user-1", {"password": "short"}, session)


def test_valid_password_hashes_via_bcrypt(service, user_stub, session):
    service.admin_update("user-1", {"password": "longenough123"}, session)
    # bcrypt hash starts with $2 prefix
    assert user_stub.password_hash.startswith("$2")


def test_empty_password_string_is_ignored(service, user_stub, session):
    """Falsy password (empty string) skips the update — pre-S23 behaviour."""
    user_stub.password_hash = "pre-existing-hash"
    service.admin_update("user-1", {"password": ""}, session)
    assert user_stub.password_hash == "pre-existing-hash"


def test_detail_field_updates_user_details_attributes(service, user_stub, session):
    service.admin_update("user-1", {"first_name": "Ada"}, session)
    assert user_stub.details.first_name == "Ada"


def test_legacy_name_field_splits_into_first_and_last(service, user_stub, session):
    service.admin_update("user-1", {"name": "Ada Lovelace"}, session)
    assert user_stub.details.first_name == "Ada"
    assert user_stub.details.last_name == "Lovelace"


def test_explicit_first_name_wins_over_legacy_name(service, user_stub, session):
    service.admin_update(
        "user-1", {"first_name": "Grace", "name": "Ada Lovelace"}, session
    )
    assert user_stub.details.first_name == "Grace"


def test_dead_balance_field_is_ignored(service, user_stub, session):
    """S94 Slice 1 — ``UserDetails.balance`` was dead (live money is
    UserTokenBalance). A stray ``balance`` key in the admin payload is now a
    no-op: it neither raises, nor sets an attribute, nor forces a details row.
    """
    service.admin_update("user-1", {"balance": "99.50"}, session)
    assert not hasattr(user_stub.details, "balance")


def test_negative_token_balance_raises(service, session):
    with pytest.raises(AdminUserUpdateError, match="negative"):
        service.admin_update("user-1", {"token_balance": -5}, session)


def test_invalid_token_balance_raises(service, session):
    with pytest.raises(AdminUserUpdateError, match="Invalid token balance"):
        service.admin_update("user-1", {"token_balance": "abc"}, session)


def test_admin_update_persists_via_repository(service, user_repo, session):
    service.admin_update("user-1", {"is_active": True}, session)
    user_repo.save.assert_called_once()


# ── admin_create ─────────────────────────────────────────────────────────


def test_admin_create_requires_email(service, session):
    with pytest.raises(AdminUserUpdateError, match="Email is required"):
        service.admin_create({"password": "longenough"}, session)


def test_admin_create_requires_password(service, session):
    with pytest.raises(AdminUserUpdateError, match="Password is required"):
        service.admin_create({"email": "u@x.io"}, session)


def test_admin_create_rejects_short_password(service, session):
    with pytest.raises(AdminUserUpdateError, match="at least 8"):
        service.admin_create({"email": "u@x.io", "password": "short"}, session)


def test_admin_create_rejects_duplicate_email(service, user_repo, session):
    user_repo.find_by_email.return_value = MagicMock()
    with pytest.raises(AdminUserUpdateError, match="already exists"):
        service.admin_create({"email": "taken@x.io", "password": "longenough"}, session)


def test_admin_create_rejects_invalid_status(service, user_repo, session):
    user_repo.find_by_email.return_value = None
    with pytest.raises(AdminUserUpdateError, match="Invalid status"):
        service.admin_create(
            {
                "email": "new@x.io",
                "password": "longenough",
                "status": "made-up",
            },
            session,
        )


def test_admin_create_rejects_invalid_role(service, user_repo, session):
    user_repo.find_by_email.return_value = None
    with pytest.raises(AdminUserUpdateError, match="Invalid role"):
        service.admin_create(
            {
                "email": "new@x.io",
                "password": "longenough",
                "role": "made-up",
            },
            session,
        )


def test_admin_create_hashes_password_and_persists(service, user_repo, session):
    user_repo.find_by_email.return_value = None
    created = service.admin_create(
        {"email": "new@x.io", "password": "longenough"}, session
    )
    user_repo.save.assert_called_once()
    assert created.email == "new@x.io"
    assert created.password_hash.startswith("$2")
    assert created.status == UserStatus.ACTIVE
    assert created.role == UserRole.USER


def test_admin_create_attaches_details_when_provided(service, user_repo, session):
    user_repo.find_by_email.return_value = None
    created = service.admin_create(
        {
            "email": "new@x.io",
            "password": "longenough",
            "details": {"first_name": "Ada", "last_name": "Lovelace"},
        },
        session,
    )
    session.add.assert_called_once()
    session.commit.assert_called_once()
    assert created.details.first_name == "Ada"
    assert created.details.last_name == "Lovelace"

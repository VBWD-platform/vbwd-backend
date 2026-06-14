"""Admin user-create must accept the server-provisioned BOT and GUEST roles.

The admin form needs to CREATE BOT accounts (chat-bot identities) and GUEST
accounts (public-visitor identity) even though neither can log in
interactively. ``UserService.admin_create`` validates ``role`` via the
``UserRole`` enum, which already includes BOT and GUEST, so no allow-list
excludes them. These tests pin that contract and re-assert the existing
auth guard still rejects interactive login for the created roles.
"""
from unittest.mock import MagicMock

import bcrypt
import pytest

from vbwd.interfaces.auth import AuthResult
from vbwd.models.enums import UserRole, UserStatus
from vbwd.services.auth_service import AuthService
from vbwd.services.user_service import UserService


@pytest.fixture
def session():
    return MagicMock()


def _admin_service():
    """A UserService whose repo echoes the saved user and reports no collision."""
    user_repo = MagicMock()
    user_repo.find_by_email.return_value = None
    user_repo.save.side_effect = lambda user: user
    return UserService(
        user_repository=user_repo,
        user_details_repository=MagicMock(),
    )


@pytest.mark.parametrize("role_value", ["BOT", "GUEST"])
def test_admin_create_persists_server_provisioned_role(role_value, session):
    service = _admin_service()

    created_user = service.admin_create(
        {
            "email": f"{role_value.lower()}@example.com",
            "password": "password123",
            "role": role_value,
        },
        session,
    )

    assert created_user.role == UserRole(role_value)
    assert created_user.status == UserStatus.ACTIVE


@pytest.mark.parametrize("role_value", ["BOT", "GUEST"])
def test_admin_created_role_still_cannot_login(role_value):
    """The auth guard must keep rejecting interactive login for these roles."""
    service = _admin_service()
    password = "password123"

    created_user = service.admin_create(
        {
            "email": f"{role_value.lower()}@example.com",
            "password": password,
            "role": role_value,
        },
        MagicMock(),
    )
    # ``admin_create`` hashes the password; give the auth repo a lookupable user.
    created_user.password_hash = bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    auth_repo = MagicMock()
    auth_repo.find_by_email.return_value = created_user
    auth_service = AuthService(user_repository=auth_repo)

    result = auth_service.login(created_user.email, password)

    assert isinstance(result, AuthResult)
    assert result.success is False
    assert result.token is None

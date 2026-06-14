"""Core GUEST role (S86.1 D-core) — public-scope-only, no interactive login.

The platform gains a ``GUEST`` user role: a server-provisioned, public-scope
identity (e.g. a widget visitor provisioned by a plugin in S86.3). GUEST
accounts are non-privileged and CANNOT log in interactively — the login path
rejects them with the same generic invalid-credentials response as a wrong
password, leaking no role information (mirrors the BOT guard, S60).
"""
import bcrypt

from vbwd.interfaces.auth import AuthResult
from vbwd.models.enums import UserRole
from vbwd.models.enums import UserStatus
from vbwd.models.user import User


class TestGuestRoleEnum:
    """GUEST exists as a first-class role, is non-admin, and round-trips."""

    def test_guest_role_value(self):
        assert UserRole.GUEST.value == "GUEST"

    def test_guest_role_parses_case_insensitively(self):
        assert UserRole("guest") is UserRole.GUEST

    def test_guest_role_round_trips_through_model(self):
        user = User()
        user.role = UserRole.GUEST
        assert user.role is UserRole.GUEST
        assert user.role.value == "GUEST"

    def test_guest_user_is_not_admin(self):
        user = User()
        user.role = UserRole.GUEST
        assert user.is_admin is False

    def test_guest_user_has_no_wildcard_permissions(self):
        user = User()
        user.role = UserRole.GUEST
        assert user.effective_permissions == []
        assert user.has_permission("anything") is False


class TestGuestLoginBlocked:
    """A GUEST account cannot authenticate interactively."""

    def _guest_user(self, password: str) -> User:
        user = User()
        user.email = "widget-guest@example.com"
        user.status = UserStatus.ACTIVE
        user.role = UserRole.GUEST
        user.password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        return user

    def _auth_service(self, user):
        from unittest.mock import Mock

        from vbwd.services.auth_service import AuthService

        repo = Mock()
        repo.find_by_email = Mock(return_value=user)
        return AuthService(user_repository=repo)

    def test_login_rejected_for_guest_even_with_correct_password(self):
        password = "useruser"
        user = self._guest_user(password)
        service = self._auth_service(user)

        result = service.login(user.email, password)

        assert isinstance(result, AuthResult)
        assert result.success is False
        assert result.token is None
        assert result.user_id is None

    def test_login_guest_rejection_is_generic_no_role_leak(self):
        """Same opaque message as a wrong password — never disclose the role."""
        password = "useruser"
        user = self._guest_user(password)
        service = self._auth_service(user)

        result = service.login(user.email, password)

        error_text = (result.error or "").lower()
        assert "guest" not in error_text
        assert "role" not in error_text
        assert "invalid" in error_text or "credentials" in error_text

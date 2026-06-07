"""Core BOT role (S60) — generic, agnostic of contact-forms / meinchat.

The platform gains a `BOT` user role for server-authored identities (e.g.
contact-form senders provisioned by the meinchat plugin). BOT accounts are
non-privileged and CANNOT log in interactively (LOCKED 2026-06-07): the
login path rejects them with the same generic invalid-credentials response
as a wrong password, leaking no role information.
"""
import bcrypt

from vbwd.interfaces.auth import AuthResult
from vbwd.models.enums import UserRole
from vbwd.models.user import User
from vbwd.models.enums import UserStatus


class TestBotRoleEnum:
    """BOT exists as a first-class role and is non-admin."""

    def test_bot_role_value(self):
        assert UserRole.BOT.value == "BOT"

    def test_bot_role_parses_case_insensitively(self):
        assert UserRole("bot") is UserRole.BOT

    def test_bot_user_is_not_admin(self):
        user = User()
        user.role = UserRole.BOT
        assert user.is_admin is False

    def test_bot_user_has_no_wildcard_permissions(self):
        user = User()
        user.role = UserRole.BOT
        assert user.effective_permissions == []
        assert user.has_permission("anything") is False


class TestBotLoginBlocked:
    """A BOT account cannot authenticate interactively."""

    def _bot_user(self, password: str) -> User:
        user = User()
        user.email = "form-bot@example.com"
        user.status = UserStatus.ACTIVE
        user.role = UserRole.BOT
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

    def test_login_rejected_for_bot_even_with_correct_password(self):
        password = "useruser"
        user = self._bot_user(password)
        service = self._auth_service(user)

        result = service.login(user.email, password)

        assert isinstance(result, AuthResult)
        assert result.success is False
        assert result.token is None
        assert result.user_id is None

    def test_login_bot_rejection_is_generic_no_role_leak(self):
        """Same opaque message as a wrong password — never disclose the role."""
        password = "useruser"
        user = self._bot_user(password)
        service = self._auth_service(user)

        result = service.login(user.email, password)

        error_text = (result.error or "").lower()
        assert "bot" not in error_text
        assert "role" not in error_text
        assert "invalid" in error_text or "credentials" in error_text

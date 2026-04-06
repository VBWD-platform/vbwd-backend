"""Unit tests for AuthService."""
import pytest
from unittest.mock import Mock
from uuid import uuid4, UUID
from datetime import datetime, timedelta
from vbwd.interfaces.auth import AuthResult
from vbwd.models.user import User
from vbwd.models.enums import UserStatus, UserRole


class TestAuthServiceRegister:
    """Test AuthService.register()"""

    @pytest.fixture
    def mock_user_repo(self):
        """Mock UserRepository."""
        repo = Mock()
        repo.find_by_email = Mock(return_value=None)
        repo.save = Mock()
        return repo

    @pytest.fixture
    def auth_service(self, mock_user_repo):
        """Create AuthService with mocked dependencies."""
        from vbwd.services.auth_service import AuthService

        return AuthService(user_repository=mock_user_repo)

    def test_register_creates_new_user(self, auth_service, mock_user_repo):
        """Test successful user registration."""
        email = "test@example.com"
        password = "SecurePassword123!"

        # Mock user creation
        mock_user = User()
        mock_user.id = uuid4()
        mock_user.email = email
        mock_user.status = UserStatus.ACTIVE
        mock_user.role = UserRole.USER
        mock_user_repo.save.return_value = mock_user

        # Call register
        result = auth_service.register(email, password)

        # Assertions
        assert isinstance(result, AuthResult)
        assert result.success is True
        assert result.user_id == mock_user.id
        assert result.token is not None
        assert result.error is None

        # Verify repository was called
        mock_user_repo.find_by_email.assert_called_once_with(email)
        mock_user_repo.save.assert_called_once()

        # Verify password was hashed (not stored as plaintext)
        save_call_args = mock_user_repo.save.call_args[0][0]
        assert save_call_args.password_hash != password
        assert len(save_call_args.password_hash) > 50  # bcrypt hash length

    def test_register_fails_if_email_exists(self, auth_service, mock_user_repo):
        """Test registration fails if email already exists."""
        email = "existing@example.com"
        password = "SecurePassword123!"

        # Mock existing user
        existing_user = User()
        existing_user.id = uuid4()
        existing_user.email = email
        mock_user_repo.find_by_email.return_value = existing_user

        # Call register
        result = auth_service.register(email, password)

        # Assertions
        assert isinstance(result, AuthResult)
        assert result.success is False
        assert result.user_id is None
        assert result.token is None
        assert "already exists" in result.error.lower()

        # Verify create was NOT called
        mock_user_repo.save.assert_not_called()

    def test_register_validates_email_format(self, auth_service, mock_user_repo):
        """Test registration validates email format."""
        invalid_emails = [
            "notanemail",
            "missing@domain",
            "@nodomain.com",
            "spaces in@email.com",
            "",
        ]

        for invalid_email in invalid_emails:
            result = auth_service.register(invalid_email, "SecurePassword123!")

            assert result.success is False
            assert result.error is not None
            assert "email" in result.error.lower() or "invalid" in result.error.lower()

        # Verify repository was never called for invalid emails
        mock_user_repo.find_by_email.assert_not_called()
        mock_user_repo.save.assert_not_called()

    def test_register_validates_password_strength(self, auth_service, mock_user_repo):
        """Test registration validates password strength."""
        weak_passwords = [
            "short",  # Too short
            "alllowercase",  # No uppercase/numbers/special
            "ALLUPPERCASE",  # No lowercase
            "NoNumbers!",  # No numbers
            "NoSpecial123",  # No special characters
        ]

        for weak_password in weak_passwords:
            result = auth_service.register("test@example.com", weak_password)

            assert result.success is False
            assert result.error is not None
            assert "password" in result.error.lower()

        # Verify repository was never called for weak passwords
        mock_user_repo.save.assert_not_called()


class TestAuthServiceLogin:
    """Test AuthService.login()"""

    @pytest.fixture
    def mock_user_repo(self):
        """Mock UserRepository."""
        repo = Mock()
        repo.find_by_email = Mock()
        return repo

    @pytest.fixture
    def auth_service(self, mock_user_repo):
        """Create AuthService with mocked dependencies."""
        from vbwd.services.auth_service import AuthService

        return AuthService(user_repository=mock_user_repo)

    def test_login_returns_token_for_valid_credentials(
        self, auth_service, mock_user_repo
    ):
        """Test successful login with valid credentials."""
        email = "test@example.com"
        password = "SecurePassword123!"

        # Create mock user with hashed password
        mock_user = User()
        mock_user.id = uuid4()
        mock_user.email = email
        mock_user.status = UserStatus.ACTIVE
        mock_user.role = UserRole.USER
        # Hash the password using bcrypt
        import bcrypt

        mock_user.password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        mock_user_repo.find_by_email.return_value = mock_user

        # Call login
        result = auth_service.login(email, password)

        # Assertions
        assert isinstance(result, AuthResult)
        assert result.success is True
        assert result.user_id == mock_user.id
        assert result.token is not None
        assert result.error is None

        # Verify token is valid JWT
        assert len(result.token.split(".")) == 3  # JWT has 3 parts

        # Verify repository was called
        mock_user_repo.find_by_email.assert_called_once_with(email)

    def test_login_fails_for_unknown_email(self, auth_service, mock_user_repo):
        """Test login fails for unknown email."""
        email = "unknown@example.com"
        password = "SecurePassword123!"

        # Mock no user found
        mock_user_repo.find_by_email.return_value = None

        # Call login
        result = auth_service.login(email, password)

        # Assertions
        assert isinstance(result, AuthResult)
        assert result.success is False
        assert result.user_id is None
        assert result.token is None
        assert (
            "invalid" in result.error.lower() or "credentials" in result.error.lower()
        )

        # Verify repository was called
        mock_user_repo.find_by_email.assert_called_once_with(email)

    def test_login_fails_for_wrong_password(self, auth_service, mock_user_repo):
        """Test login fails for wrong password."""
        email = "test@example.com"
        correct_password = "CorrectPassword123!"
        wrong_password = "WrongPassword123!"

        # Create mock user with correct password hash
        mock_user = User()
        mock_user.id = uuid4()
        mock_user.email = email
        mock_user.status = UserStatus.ACTIVE
        mock_user.role = UserRole.USER
        import bcrypt

        mock_user.password_hash = bcrypt.hashpw(
            correct_password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        mock_user_repo.find_by_email.return_value = mock_user

        # Call login with wrong password
        result = auth_service.login(email, wrong_password)

        # Assertions
        assert isinstance(result, AuthResult)
        assert result.success is False
        assert result.user_id is None
        assert result.token is None
        assert (
            "invalid" in result.error.lower() or "credentials" in result.error.lower()
        )

    def test_login_fails_for_inactive_user(self, auth_service, mock_user_repo):
        """Test login fails for inactive user."""
        email = "inactive@example.com"
        password = "SecurePassword123!"

        # Create mock suspended user
        mock_user = User()
        mock_user.id = uuid4()
        mock_user.email = email
        mock_user.status = UserStatus.SUSPENDED
        import bcrypt

        mock_user.password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        mock_user_repo.find_by_email.return_value = mock_user

        # Call login
        result = auth_service.login(email, password)

        # Assertions
        assert isinstance(result, AuthResult)
        assert result.success is False
        assert result.user_id is None
        assert result.token is None
        assert (
            "inactive" in result.error.lower()
            or "disabled" in result.error.lower()
            or "suspended" in result.error.lower()
        )


class TestAuthServiceToken:
    """Test AuthService token operations"""

    @pytest.fixture
    def mock_user_repo(self):
        """Mock UserRepository."""
        return Mock()

    @pytest.fixture
    def auth_service(self, mock_user_repo):
        """Create AuthService with mocked dependencies."""
        from vbwd.services.auth_service import AuthService

        return AuthService(user_repository=mock_user_repo)

    def test_verify_token_returns_user_id(self, auth_service):
        """Test token verification returns user_id."""
        # Create a valid token first
        user_id = uuid4()
        email = "test@example.com"

        # Generate token (we'll need to implement this)
        import jwt
        from vbwd.config import get_config

        config = get_config()

        payload = {
            "user_id": str(user_id),
            "email": email,
            "exp": datetime.utcnow() + timedelta(hours=24),
        }
        token = jwt.encode(payload, config.SECRET_KEY, algorithm="HS256")

        # Verify token
        result_user_id = auth_service.verify_token(token)

        # Assertions
        assert result_user_id is not None
        assert isinstance(result_user_id, UUID)
        assert result_user_id == user_id

    def test_verify_token_returns_none_for_invalid_token(self, auth_service):
        """Test token verification returns None for invalid token."""
        invalid_tokens = [
            "invalid.token.format",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid",
            "",
            "not-a-jwt",
        ]

        for invalid_token in invalid_tokens:
            result = auth_service.verify_token(invalid_token)
            assert result is None

    def test_verify_token_returns_none_for_expired_token(self, auth_service):
        """Test token verification returns None for expired token."""
        user_id = uuid4()
        email = "test@example.com"

        # Generate expired token
        import jwt
        from vbwd.config import get_config

        config = get_config()

        payload = {
            "user_id": str(user_id),
            "email": email,
            "exp": datetime.utcnow() - timedelta(hours=1),  # Expired 1 hour ago
        }
        expired_token = jwt.encode(payload, config.SECRET_KEY, algorithm="HS256")

        # Verify expired token
        result = auth_service.verify_token(expired_token)

        # Assertions
        assert result is None


class TestAuthServicePassword:
    """Test AuthService password operations"""

    @pytest.fixture
    def mock_user_repo(self):
        """Mock UserRepository."""
        return Mock()

    @pytest.fixture
    def auth_service(self, mock_user_repo):
        """Create AuthService with mocked dependencies."""
        from vbwd.services.auth_service import AuthService

        return AuthService(user_repository=mock_user_repo)

    def test_hash_password_returns_bcrypt_hash(self, auth_service):
        """Test password hashing returns bcrypt hash."""
        password = "SecurePassword123!"

        # Hash password
        hashed = auth_service.hash_password(password)

        # Assertions
        assert hashed is not None
        assert isinstance(hashed, str)
        assert len(hashed) > 50  # bcrypt hash length
        assert hashed != password  # Not plaintext
        assert hashed.startswith("$2b$")  # bcrypt signature

    def test_hash_password_generates_unique_salts(self, auth_service):
        """Test password hashing generates unique salts."""
        password = "SecurePassword123!"

        # Hash same password twice
        hash1 = auth_service.hash_password(password)
        hash2 = auth_service.hash_password(password)

        # Assertions - should be different due to unique salts
        assert hash1 != hash2

    def test_verify_password_returns_true_for_match(self, auth_service):
        """Test password verification returns True for matching password."""
        password = "SecurePassword123!"

        # Hash password
        hashed = auth_service.hash_password(password)

        # Verify password
        result = auth_service.verify_password(password, hashed)

        # Assertions
        assert result is True

    def test_verify_password_returns_false_for_mismatch(self, auth_service):
        """Test password verification returns False for wrong password."""
        correct_password = "CorrectPassword123!"
        wrong_password = "WrongPassword123!"

        # Hash correct password
        hashed = auth_service.hash_password(correct_password)

        # Verify with wrong password
        result = auth_service.verify_password(wrong_password, hashed)

        # Assertions
        assert result is False

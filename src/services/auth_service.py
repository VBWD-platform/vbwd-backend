"""Authentication service implementation."""
import re
import bcrypt
import jwt
from datetime import timedelta
from src.utils.datetime_utils import utcnow
from typing import Optional
from uuid import UUID
from src.interfaces.auth import IAuthService, AuthResult, UserData
from src.repositories.user_repository import UserRepository
from src.models.user import User
from src.models.enums import UserStatus, UserRole
from src.config import get_config


class AuthService(IAuthService):
    """Service for user authentication and authorization."""

    def __init__(self, user_repository: UserRepository):
        """Initialize AuthService.

        Args:
            user_repository: Repository for user data access
        """
        self._user_repo = user_repository
        self._config = get_config()

    def register(self, email: str, password: str) -> AuthResult:
        """Register new user.

        Args:
            email: User email address
            password: User password (plaintext)

        Returns:
            AuthResult with success status and token if successful
        """
        # Validate email format
        if not self._validate_email(email):
            return AuthResult(success=False, error="Invalid email format")

        # Validate password strength
        password_error = self._validate_password_strength(password)
        if password_error:
            return AuthResult(success=False, error=password_error)

        # Check if user already exists
        existing_user = self._user_repo.find_by_email(email)
        if existing_user:
            return AuthResult(
                success=False, error="User with this email already exists"
            )

        # Hash password
        password_hash = self.hash_password(password)

        # Create user
        new_user = User()
        new_user.email = email
        new_user.password_hash = password_hash
        new_user.status = UserStatus.ACTIVE
        new_user.role = UserRole.USER

        created_user = self._user_repo.save(new_user)

        # Generate token
        token = self._generate_token(created_user.id, created_user.email)  # type: ignore[arg-type]

        return AuthResult(success=True, user_id=created_user.id, token=token)  # type: ignore[arg-type]

    def login(self, email: str, password: str) -> AuthResult:
        """Login user and return JWT token.

        Args:
            email: User email address
            password: User password (plaintext)

        Returns:
            AuthResult with success status and token if successful
        """
        # Find user by email
        user = self._user_repo.find_by_email(email)
        if not user:
            return AuthResult(success=False, error="Invalid credentials")

        # Check if user is active
        if user.status != UserStatus.ACTIVE:
            return AuthResult(success=False, error="User account is inactive")

        # Verify password
        if not self.verify_password(password, user.password_hash):
            return AuthResult(success=False, error="Invalid credentials")

        # Generate token
        token = self._generate_token(user.id, user.email)  # type: ignore[arg-type]

        # Build user data for response
        user_data = UserData(
            id=str(user.id),
            email=user.email,
            name=user.email.split("@")[0],  # Use email prefix as name if no name field
            roles=[user.role.value] if user.role else ["user"],
        )

        return AuthResult(success=True, user_id=user.id, token=token, user=user_data)  # type: ignore[arg-type]

    def verify_token(self, token: str) -> Optional[UUID]:
        """Verify JWT token and return user_id if valid.

        Args:
            token: JWT token string

        Returns:
            User UUID if token is valid, None otherwise
        """
        try:
            payload = jwt.decode(token, self._config.SECRET_KEY, algorithms=["HS256"])
            user_id_str = payload.get("user_id")
            if user_id_str:
                return UUID(user_id_str)
            return None
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
        except (ValueError, KeyError):
            return None

    def hash_password(self, password: str) -> str:
        """Hash password using bcrypt.

        Args:
            password: Plaintext password

        Returns:
            Bcrypt hashed password
        """
        password_bytes = password.encode("utf-8")
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode("utf-8")

    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify password against hash.

        Args:
            password: Plaintext password
            hashed: Bcrypt hashed password

        Returns:
            True if password matches hash, False otherwise
        """
        try:
            password_bytes = password.encode("utf-8")
            hashed_bytes = hashed.encode("utf-8")
            return bcrypt.checkpw(password_bytes, hashed_bytes)
        except Exception:
            return False

    def _generate_token(self, user_id: UUID, email: str) -> str:
        """Generate JWT token for user.

        Args:
            user_id: User UUID
            email: User email

        Returns:
            JWT token string
        """
        expiration_hours = getattr(self._config, "JWT_EXPIRATION_HOURS", 24)
        payload = {
            "user_id": str(user_id),
            "email": email,
            "exp": utcnow() + timedelta(hours=expiration_hours),
            "iat": utcnow(),
        }
        token = jwt.encode(payload, self._config.SECRET_KEY, algorithm="HS256")
        return token

    def _validate_email(self, email: str) -> bool:
        """Validate email format.

        Args:
            email: Email address to validate

        Returns:
            True if email is valid, False otherwise
        """
        if not email:
            return False

        # RFC 5322 simplified email regex
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return re.match(email_pattern, email) is not None

    def _validate_password_strength(self, password: str) -> Optional[str]:
        """Validate password strength.

        Args:
            password: Password to validate

        Returns:
            Error message if password is weak, None if password is strong
        """
        if len(password) < 8:
            return "Password must be at least 8 characters long"

        if not re.search(r"[a-z]", password):
            return "Password must contain at least one lowercase letter"

        if not re.search(r"[A-Z]", password):
            return "Password must contain at least one uppercase letter"

        if not re.search(r"\d", password):
            return "Password must contain at least one number"

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            return "Password must contain at least one special character"

        return None

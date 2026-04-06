"""Authentication interfaces."""
from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass
from uuid import UUID


@dataclass
class UserData:
    """User data returned in auth responses."""

    id: str
    email: str
    name: Optional[str] = None
    role: Optional[str] = None
    is_admin: Optional[bool] = None
    access_levels: Optional[list] = None
    permissions: Optional[list] = None
    user_access_levels: Optional[list] = None
    user_permissions: Optional[list] = None


@dataclass
class AuthResult:
    """Result of authentication operation."""

    success: bool
    user_id: Optional[UUID] = None
    token: Optional[str] = None
    error: Optional[str] = None
    user: Optional[UserData] = None


class IAuthService(ABC):
    """Interface for authentication service."""

    @abstractmethod
    def register(self, email: str, password: str) -> AuthResult:
        """Register new user."""
        pass

    @abstractmethod
    def login(self, email: str, password: str) -> AuthResult:
        """Login user and return JWT token."""
        pass

    @abstractmethod
    def verify_token(self, token: str) -> Optional[UUID]:
        """Verify JWT token and return user_id if valid."""
        pass

    @abstractmethod
    def hash_password(self, password: str) -> str:
        """Hash password using bcrypt."""
        pass

    @abstractmethod
    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify password against hash."""
        pass


class IUserService(ABC):
    """Interface for user management service."""

    @abstractmethod
    def get_user(self, user_id: UUID):
        """Get user by ID."""
        pass

    @abstractmethod
    def get_user_details(self, user_id: UUID):
        """Get user details."""
        pass

    @abstractmethod
    def update_user_details(self, user_id: UUID, details: dict):
        """Update user details."""
        pass

    @abstractmethod
    def update_user_status(self, user_id: UUID, status):
        """Update user status."""
        pass

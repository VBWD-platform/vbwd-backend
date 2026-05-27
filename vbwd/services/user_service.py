"""User management service implementation."""
from typing import Any, Mapping, Optional, cast
from uuid import UUID

import bcrypt

from vbwd.interfaces.auth import IUserService
from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User
from vbwd.models.user_details import UserDetails
from vbwd.repositories.user_details_repository import UserDetailsRepository
from vbwd.repositories.user_repository import UserRepository


class AdminUserUpdateError(ValueError):
    """Raised when an admin user-update payload is invalid (S23)."""


_USER_DETAIL_FIELDS = (
    "first_name",
    "last_name",
    "phone",
    "address_line_1",
    "address_line_2",
    "city",
    "postal_code",
    "country",
    "company",
    "tax_number",
)


class UserService(IUserService):
    """Service for user management operations."""

    def __init__(
        self,
        user_repository: UserRepository,
        user_details_repository: UserDetailsRepository,
    ):
        """Initialize UserService.

        Args:
            user_repository: Repository for user data access
            user_details_repository: Repository for user details data access
        """
        self._user_repo = user_repository
        self._user_details_repo = user_details_repository

    def get_user(self, user_id: UUID) -> Optional[User]:
        """Get user by ID.

        Args:
            user_id: User UUID

        Returns:
            User if found, None otherwise
        """
        return self._user_repo.find_by_id(user_id)

    def get_user_details(self, user_id: UUID) -> Optional[UserDetails]:
        """Get user details.

        Args:
            user_id: User UUID

        Returns:
            UserDetails if found, None otherwise
        """
        return self._user_details_repo.find_by_user_id(user_id)

    def update_user_details(
        self, user_id: UUID, details: dict
    ) -> Optional[UserDetails]:
        """Update user details.

        Creates new user details record if none exists.

        Args:
            user_id: User UUID
            details: Dictionary of details to update

        Returns:
            Updated UserDetails
        """
        # Try to find existing details
        user_details = self._user_details_repo.find_by_user_id(user_id)

        if user_details:
            # Update existing details
            for key, value in details.items():
                if hasattr(user_details, key):
                    setattr(user_details, key, value)
            return self._user_details_repo.update(user_details)
        else:
            # Create new details
            user_details = UserDetails()
            user_details.user_id = user_id

            # Set provided details
            for key, value in details.items():
                if hasattr(user_details, key):
                    setattr(user_details, key, value)

            return self._user_details_repo.save(user_details)

    def update_user_status(self, user_id: UUID, status: UserStatus) -> Optional[User]:
        """Update user status.

        Args:
            user_id: User UUID
            status: New user status

        Returns:
            Updated User if found, None otherwise
        """
        user = self._user_repo.find_by_id(user_id)

        if user:
            user.status = status
            return self._user_repo.update(user)

        return None

    # ------------------------------------------------------------------
    # Admin create (S23 — extracted from admin/users.py)
    # ------------------------------------------------------------------

    def admin_create(
        self,
        payload: Mapping[str, Any],
        session,
    ) -> User:
        """Validate payload and create a user (with optional details).

        Raises:
            AdminUserUpdateError — required field missing, password too
                short, invalid status/role, duplicate email.
        """
        email = payload.get("email")
        password = payload.get("password")
        if not email:
            raise AdminUserUpdateError("Email is required")
        if not password:
            raise AdminUserUpdateError("Password is required")
        if len(password) < 8:
            raise AdminUserUpdateError("Password must be at least 8 characters")
        if self._user_repo.find_by_email(email):
            raise AdminUserUpdateError("User with this email already exists")

        try:
            status = UserStatus(payload.get("status", "ACTIVE"))
        except ValueError as bad_status:
            raise AdminUserUpdateError(
                f"Invalid status: {payload.get('status')}"
            ) from bad_status
        try:
            role = UserRole(payload.get("role", "USER"))
        except ValueError as bad_role:
            raise AdminUserUpdateError(
                f"Invalid role: {payload.get('role')}"
            ) from bad_role

        password_bytes = password.encode("utf-8")
        password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")

        user = User()
        user.email = email
        user.password_hash = password_hash
        user.status = status
        user.role = role
        created_user = self._user_repo.save(user)

        details_payload = payload.get("details")
        if details_payload:
            self._attach_details_on_create(created_user, details_payload, session)

        return created_user

    def _attach_details_on_create(
        self, user: User, details_payload: Mapping[str, Any], session
    ) -> None:
        user_details = UserDetails()
        user_details.user_id = user.id
        for field in (
            "first_name",
            "last_name",
            "address_line_1",
            "address_line_2",
            "city",
            "postal_code",
            "country",
            "phone",
        ):
            setattr(user_details, field, details_payload.get(field))
        session.add(user_details)
        session.commit()
        user.details = user_details

    # ------------------------------------------------------------------
    # Admin update orchestration (S23 — extracted from admin/users.py)
    # ------------------------------------------------------------------

    def admin_update(
        self,
        user_id: str,
        payload: Mapping[str, Any],
        session,
    ) -> Optional[User]:
        """Apply an admin-side update payload to a user.

        The route layer calls this; the route stays transport-only.
        ``session`` is passed in because token-balance and details
        creation use the active transaction (until those repos own
        their own transactional behaviour).

        Returns the persisted user, or ``None`` if no user with that id
        exists. Raises ``AdminUserUpdateError`` on validation failure.
        """
        user = self._user_repo.find_by_id(user_id)
        if user is None:
            return None

        self._apply_status(user, payload)
        self._apply_role(user, payload)
        self._apply_password(user, payload)
        self._ensure_details_row(user, payload, session)
        self._apply_detail_fields(user, payload)
        self._apply_legacy_name(user, payload)
        self._apply_balance(user, payload)
        self._apply_token_balance(user, payload, session)

        return self._user_repo.save(user)

    # ── private helpers (each does one thing) ─────────────────────────

    def _apply_status(self, user: User, payload: Mapping[str, Any]) -> None:
        # Frontend may send is_active OR status; both map onto UserStatus.
        if "is_active" in payload:
            user.status = (
                UserStatus.ACTIVE if payload["is_active"] else UserStatus.SUSPENDED
            )
        if "status" in payload:
            try:
                user.status = UserStatus(payload["status"])
            except ValueError as bad_status:
                raise AdminUserUpdateError(
                    f"Invalid status: {payload['status']}"
                ) from bad_status

    def _apply_role(self, user: User, payload: Mapping[str, Any]) -> None:
        if "role" not in payload:
            return
        try:
            user.role = UserRole(payload["role"])
        except ValueError as bad_role:
            raise AdminUserUpdateError(f"Invalid role: {payload['role']}") from bad_role

    def _apply_password(self, user: User, payload: Mapping[str, Any]) -> None:
        new_password = payload.get("password")
        if not new_password:
            return
        if len(new_password) < 8:
            raise AdminUserUpdateError("Password must be at least 8 characters")
        password_bytes = new_password.encode("utf-8")
        user.password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode(
            "utf-8"
        )

    def _ensure_details_row(
        self, user: User, payload: Mapping[str, Any], session
    ) -> None:
        # Create a UserDetails row only if the payload touches a details field.
        has_detail = any(field in payload for field in _USER_DETAIL_FIELDS)
        has_name = bool(payload.get("name"))
        has_balance = "balance" in payload
        if not (has_detail or has_name or has_balance):
            return
        if user.details:
            return
        user_details = UserDetails()
        user_details.user_id = user.id
        session.add(user_details)
        session.flush()
        session.refresh(user)

    def _apply_detail_fields(self, user: User, payload: Mapping[str, Any]) -> None:
        if not user.details:
            return
        for field in _USER_DETAIL_FIELDS:
            if field in payload:
                setattr(user.details, field, payload[field] or None)

    def _apply_legacy_name(self, user: User, payload: Mapping[str, Any]) -> None:
        # Backward-compat: frontend used to send a combined `name` field.
        # Only honour it when no explicit first/last is provided.
        name = payload.get("name")
        if not name:
            return
        if any(field in payload for field in _USER_DETAIL_FIELDS):
            return
        # SQLAlchemy relationship descriptor typing — cast the instance-level
        # attribute back to the concrete model type for mypy.
        details = cast(Optional[UserDetails], user.details)
        if details is None:
            return
        first, _, last = name.strip().partition(" ")
        details.first_name = first
        details.last_name = last

    def _apply_balance(self, user: User, payload: Mapping[str, Any]) -> None:
        if "balance" not in payload:
            return
        try:
            balance_value = float(payload["balance"])
        except (TypeError, ValueError) as bad_balance:
            raise AdminUserUpdateError("Invalid balance value") from bad_balance
        if balance_value < 0:
            raise AdminUserUpdateError("Balance cannot be negative")
        # SQLAlchemy relationship descriptor typing — cast the instance-level
        # attribute back to the concrete model type for mypy.
        details = cast(Optional[UserDetails], user.details)
        if details is None:
            return
        details.balance = balance_value

    def _apply_token_balance(
        self, user: User, payload: Mapping[str, Any], session
    ) -> None:
        if "token_balance" not in payload:
            return
        try:
            token_value = int(payload["token_balance"])
        except (TypeError, ValueError) as bad_token_balance:
            raise AdminUserUpdateError(
                "Invalid token balance value"
            ) from bad_token_balance
        if token_value < 0:
            raise AdminUserUpdateError("Token balance cannot be negative")
        # Local import — token balance model lives next to invoice; importing
        # at module-top would pull the full invoice module on every UserService
        # use.
        from vbwd.models.user_token_balance import UserTokenBalance

        existing = session.query(UserTokenBalance).filter_by(user_id=user.id).first()
        if existing:
            existing.balance = token_value
        else:
            session.add(UserTokenBalance(user_id=user.id, balance=token_value))

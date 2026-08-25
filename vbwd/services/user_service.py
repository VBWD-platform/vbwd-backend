"""User management service implementation."""
from typing import Any, Mapping, Optional, cast
from uuid import UUID

import bcrypt

from vbwd.interfaces.auth import IUserService
from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User
from vbwd.models.user_details import UserDetails, validate_account_type
from vbwd.registries.user_provisioning_guard_registry import (
    UserProvisioningRequest,
    run_user_provisioning_guards,
)
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
    "state",
    "postal_code",
    "country",
    "company",
    "tax_number",
    "account_type",
)


class UserService(IUserService):
    """Service for user management operations."""

    def __init__(
        self,
        user_repository: UserRepository,
        user_details_repository: UserDetailsRepository,
        token_service,
    ):
        """Initialize UserService.

        Args:
            user_repository: Repository for user data access
            user_details_repository: Repository for user details data access
            token_service: Core token service — the single home for every token
                movement, so an admin balance change produces a
                ``TokenTransaction`` and fires the movement hooks like any other
                (S138.0). Required, not optional-with-fallback: an absent
                collaborator would be a latent ``AttributeError`` on the one
                path that must never silently skip.
        """
        self._user_repo = user_repository
        self._user_details_repo = user_details_repository
        self._token_service = token_service

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
            self._validate_account_type(user_details, details)
            return self._user_details_repo.update(user_details)
        else:
            # Create new details
            user_details = UserDetails()
            user_details.user_id = user_id

            # Set provided details
            for key, value in details.items():
                if hasattr(user_details, key):
                    setattr(user_details, key, value)

            self._validate_account_type(user_details, details)
            return self._user_details_repo.save(user_details)

    def _validate_account_type(
        self, user_details: UserDetails, payload: Mapping[str, Any]
    ) -> None:
        """Validate account-type only when the payload touches it (S74).

        Validation runs against the *resulting* row state so a payload that
        only flips ``account_type`` to business is rejected unless a company
        is already (or simultaneously) set.
        """
        if "account_type" not in payload:
            return
        validate_account_type(user_details.account_type, user_details.company)

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

        # Plugin-contributed provisioning guards run BEFORE the user is
        # persisted. A guard may veto (raise UserProvisioningBlocked, which the
        # route turns into a structured 402/403) or perform a side effect. Core
        # runs the guards and names no policy; with none registered this is a
        # no-op and creation is unchanged.
        run_user_provisioning_guards(
            UserProvisioningRequest(
                action="create",
                email=email,
                role=role,
                acting_user_id=self._acting_user_id(),
                session=session,
            )
        )

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

    @staticmethod
    def _acting_user_id() -> Optional[str]:
        """The authenticated user performing the action (``g.user_id``).

        Read lazily so the service stays usable outside a request context
        (unit tests, CLI seeding), where it returns ``None``.
        """
        try:
            from flask import g

            return getattr(g, "user_id", None)
        except RuntimeError:
            return None

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
            "state",
            "postal_code",
            "country",
            "phone",
            "company",
            "tax_number",
        ):
            setattr(user_details, field, details_payload.get(field))
        if "account_type" in details_payload:
            user_details.account_type = details_payload["account_type"]
        validate_account_type(user_details.account_type, user_details.company)
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
        details = cast(Optional[UserDetails], user.details)
        if details is not None:
            self._validate_account_type(details, payload)
        self._apply_legacy_name(user, payload)
        self._apply_token_balance(user, payload)
        self._apply_group_slugs(user, payload)

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
        if not (has_detail or has_name):
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

    def _apply_token_balance(self, user: User, payload: Mapping[str, Any]) -> None:
        """Set the user's token balance to ``payload["token_balance"]``.

        Absolute from the API's point of view, a DELTA underneath: it used to do
        ``existing.balance = token_value``, which wrote no ``TokenTransaction``
        and fired nothing — the balance could diverge from the sum of its own
        transactions with no trace. Routing the difference through
        ``TokenService`` makes ``balance == sum(TokenTransaction.amount)`` a real
        invariant and lets a movement hook see the adjustment.

        ``commit=False``: the movement composes with the rest of
        ``admin_update``, which commits once via ``self._user_repo.save``.
        """
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

        # Local import — the enum lives with the token models; importing at
        # module-top would pull them on every UserService use.
        from vbwd.models.enums import TokenTransactionType

        delta = token_value - self._token_service.get_balance(user.id)
        if delta > 0:
            self._token_service.credit_tokens(
                user_id=user.id,
                amount=delta,
                transaction_type=TokenTransactionType.ADJUSTMENT,
                description=f"Admin set token balance to {token_value}",
                commit=False,
            )
        elif delta < 0:
            self._token_service.debit_tokens(
                user_id=user.id,
                amount=-delta,
                transaction_type=TokenTransactionType.ADJUSTMENT,
                description=f"Admin set token balance to {token_value}",
                commit=False,
            )

    def _apply_group_slugs(self, user: User, payload: Mapping[str, Any]) -> None:
        # S73 — the core user update payload may carry a replace-set of group
        # slugs. Membership is written through the core port (never importing the
        # UserGroup model here), so admin-controlled groups round-trip on save.
        if "group_slugs" not in payload:
            return
        slugs = payload["group_slugs"]
        if not isinstance(slugs, (list, tuple)):
            raise AdminUserUpdateError("group_slugs must be a list")
        from uuid import UUID

        from vbwd.services.user_group_membership import (
            resolve_user_group_membership,
        )

        resolve_user_group_membership().set_user_groups(
            UUID(str(user.id)), [str(slug) for slug in slugs if slug]
        )

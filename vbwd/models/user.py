"""User domain model."""
from vbwd.extensions import db
from vbwd.models.base import BaseModel
from vbwd.models.enums import UserStatus, UserRole


class User(BaseModel):
    """
    User account model.

    Stores core authentication data. Personal details
    are stored separately in UserDetails for GDPR compliance.
    """

    __tablename__ = "vbwd_user"

    email = db.Column(
        db.String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    password_hash = db.Column(db.String(255), nullable=False)
    status = db.Column(
        db.Enum(UserStatus, native_enum=True, create_constraint=False),
        nullable=False,
        default=UserStatus.PENDING,
        index=True,
    )
    role = db.Column(
        db.Enum(UserRole, native_enum=True, create_constraint=False),
        nullable=False,
        default=UserRole.USER,
    )
    payment_customer_id = db.Column(
        db.String(255), unique=True, nullable=True, index=True
    )
    has_used_trial = db.Column(db.Boolean, nullable=False, default=False)

    # Relationships
    details = db.relationship(
        "UserDetails",
        backref="user",
        uselist=False,
        lazy="joined",
        cascade="all, delete-orphan",
    )
    subscriptions = db.relationship(
        "Subscription",
        backref="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    invoices = db.relationship(
        "UserInvoice",
        backref="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    cases = db.relationship(
        "UserCase",
        backref="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def _get_access_levels(self) -> list:
        """Get assigned access levels (RBAC roles)."""
        roles = getattr(self, "assigned_roles", None)
        if roles is not None:
            return list(roles)
        return []

    @property
    def is_active(self) -> bool:
        """Check if user account is active."""
        return self.status == UserStatus.ACTIVE

    @property
    def is_admin(self) -> bool:
        """Check if user can access admin panel."""
        return self.role in (UserRole.SUPER_ADMIN, UserRole.ADMIN)

    @property
    def effective_permissions(self) -> list[str]:
        """Get effective permissions based on role."""
        if self.role == UserRole.SUPER_ADMIN:
            return ["*"]
        permissions: set[str] = set()
        for access_level in self._get_access_levels():
            for perm in list(access_level.permissions):
                permissions.add(perm.name)
        return sorted(permissions)

    def has_permission(self, permission_name: str) -> bool:
        """Check if user has a specific admin permission."""
        if self.role == UserRole.SUPER_ADMIN:
            return True
        access_levels = self._get_access_levels()
        # Legacy fallback: ADMIN users with no RBAC roles get all permissions
        if self.role == UserRole.ADMIN and not access_levels:
            return True
        for access_level in access_levels:
            if access_level.has_permission(permission_name):
                return True
        return False

    def _get_user_access_levels(self) -> list:
        """Get assigned user access levels (fe-user permissions)."""
        levels = getattr(self, "assigned_user_access_levels", None)
        if levels is not None:
            return list(levels)
        return []

    @property
    def effective_user_permissions(self) -> list[str]:
        """Get all user-facing permissions from assigned user access levels."""
        permissions: set[str] = set()
        for level in self._get_user_access_levels():
            for perm in list(level.permissions):
                permissions.add(perm.name)
        return sorted(permissions)

    def has_user_permission(self, permission_name: str) -> bool:
        """Check if user has a specific user-facing permission."""
        for level in self._get_user_access_levels():
            if level.has_permission(permission_name):
                return True
        return False

    def to_dict(self) -> dict:
        """Convert to dictionary, excluding sensitive data."""
        name = None
        if self.details:
            name_parts = []
            if self.details.first_name:
                name_parts.append(self.details.first_name)
            if self.details.last_name:
                name_parts.append(self.details.last_name)
            name = " ".join(name_parts) if name_parts else None

        result = {
            "id": str(self.id),
            "email": self.email,
            "name": name,
            "status": self.status.value,
            "is_active": self.is_active,
            "role": self.role.value,
            "is_admin": self.is_admin,
            "access_levels": [
                {
                    "id": str(r.id),
                    "slug": r.slug,
                    "name": r.name,
                }
                for r in self._get_access_levels()
            ],
            "permissions": self.effective_permissions,
            "user_access_levels": [
                {
                    "id": str(level.id),
                    "slug": level.slug,
                    "name": level.name,
                }
                for level in self._get_user_access_levels()
            ],
            "user_permissions": self.effective_user_permissions,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat() if self.updated_at else None
            ),
        }

        if self.details:
            result["details"] = self.details.to_dict()

        tb = getattr(self, "token_balance", None)
        result["token_balance"] = tb.balance if tb else 0

        return result

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}')>"

"""AdminRole and Permission models for RBAC (System B — gates ``/admin``)."""
from vbwd.extensions import db
from vbwd.models.base import BaseModel


# Association table for admin-role-permission many-to-many.
# Module-level variable name kept as ``role_permissions`` for back-compat; only
# the table-name literal changed to ``vbwd_admin_role_permissions``.
role_permissions = db.Table(
    "vbwd_admin_role_permissions",
    db.Column(
        "role_id",
        db.UUID(as_uuid=True),
        db.ForeignKey("vbwd_admin_role.id"),
        primary_key=True,
    ),
    db.Column(
        "permission_id",
        db.UUID(as_uuid=True),
        db.ForeignKey("vbwd_permission.id"),
        primary_key=True,
    ),
)

# Association table for user-admin-role many-to-many.
# Module-level variable name kept as ``user_roles`` for back-compat; only the
# table-name literal changed to ``vbwd_user_admin_role``.
user_roles = db.Table(
    "vbwd_user_admin_role",
    db.Column(
        "user_id",
        db.UUID(as_uuid=True),
        db.ForeignKey("vbwd_user.id"),
        primary_key=True,
    ),
    db.Column(
        "role_id",
        db.UUID(as_uuid=True),
        db.ForeignKey("vbwd_admin_role.id"),
        primary_key=True,
    ),
)


class AdminRole(BaseModel):
    """
    Admin-role model for RBAC (System B — gates ``/admin``).

    Roles group permissions together and can be assigned to users.
    System roles (is_system=True) cannot be deleted.
    """

    __tablename__ = "vbwd_admin_role"

    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.String(500))
    is_system = db.Column(db.Boolean, default=False, nullable=False)

    # Many-to-many: Role <-> Permission
    permissions = db.relationship(
        "Permission",
        secondary=role_permissions,
        backref=db.backref("roles", lazy="dynamic"),
        lazy="joined",
    )

    # Many-to-many: User <-> Role
    users = db.relationship(
        "User",
        secondary=user_roles,
        backref=db.backref("assigned_roles", lazy="joined"),
        lazy="dynamic",
    )

    def has_permission(self, permission_name: str) -> bool:
        """Check if role grants a specific permission. Supports wildcards."""
        perms = list(self.permissions)
        for perm in perms:
            if perm.name == "*":
                return True
            if perm.name == permission_name:
                return True
            if perm.name.endswith(".*") and permission_name.startswith(perm.name[:-1]):
                return True
        return False

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        perms = list(self.permissions)
        return {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "is_system": self.is_system,
            "permissions": [p.name for p in perms],
        }

    def __repr__(self) -> str:
        return f"<AdminRole(slug='{self.slug}')>"


# Transitional back-compat alias: plugin tests + some core code import ``Role``.
Role = AdminRole


class Permission(BaseModel):
    """
    Permission model for RBAC.

    Permissions define granular access rights.
    Format: resource.action (e.g., users.view, subscriptions.manage)
    """

    __tablename__ = "vbwd_permission"

    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.String(255))
    resource = db.Column(db.String(50), nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "resource": self.resource,
            "action": self.action,
        }

    def __repr__(self) -> str:
        return f"<Permission(name='{self.name}')>"

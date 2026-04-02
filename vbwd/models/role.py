"""Role and Permission models for RBAC."""
from vbwd.extensions import db
from vbwd.models.base import BaseModel


# Association table for role-permission many-to-many
role_permissions = db.Table(
    "vbwd_role_permissions",
    db.Column(
        "role_id", db.UUID(as_uuid=True), db.ForeignKey("vbwd_role.id"), primary_key=True
    ),
    db.Column(
        "permission_id",
        db.UUID(as_uuid=True),
        db.ForeignKey("vbwd_permission.id"),
        primary_key=True,
    ),
)

# Association table for user-role many-to-many
user_roles = db.Table(
    "vbwd_user_roles",
    db.Column(
        "user_id", db.UUID(as_uuid=True), db.ForeignKey("vbwd_user.id"), primary_key=True
    ),
    db.Column(
        "role_id", db.UUID(as_uuid=True), db.ForeignKey("vbwd_role.id"), primary_key=True
    ),
)


class Role(BaseModel):
    """
    Role model for RBAC.

    Roles group permissions together and can be assigned to users.
    System roles (is_system=True) cannot be deleted.
    """

    __tablename__ = "vbwd_role"

    name = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.String(255))
    is_system = db.Column(db.Boolean, default=False)

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
        backref=db.backref("rbac_roles", lazy="dynamic"),
        lazy="dynamic",
    )

    def has_permission(self, permission_name: str) -> bool:
        """Check if role has a specific permission."""
        return any(p.name == permission_name for p in self.permissions)  # type: ignore[attr-defined]

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "is_system": self.is_system,
            "permissions": [p.name for p in self.permissions],  # type: ignore[attr-defined]
        }

    def __repr__(self) -> str:
        return f"<Role(name='{self.name}')>"


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

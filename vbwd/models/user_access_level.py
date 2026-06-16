"""Access Level model for fe-user permission control."""
from vbwd.extensions import db
from vbwd.models.base import BaseModel


# Association: access_level <-> permission (many-to-many)
user_access_level_permissions = db.Table(
    "vbwd_access_level_permissions",
    db.Column(
        "user_access_level_id",
        db.UUID(as_uuid=True),
        db.ForeignKey("vbwd_access_level.id"),
        primary_key=True,
    ),
    db.Column(
        "permission_id",
        db.UUID(as_uuid=True),
        db.ForeignKey("vbwd_permission.id"),
        primary_key=True,
    ),
)

# Association: user <-> user_access_level (many-to-many)
user_user_access_levels = db.Table(
    # S94 Slice 5 — renamed from the ambiguous ``vbwd_user_user_access_levels``
    # to match the S73 ``vbwd_user_group_rel`` convention. The Python handle +
    # ORM ``assigned_user_access_levels`` backref are unchanged, so services/
    # plugins are untouched; only the backing table moved.
    "vbwd_user_access_level_rel",
    db.Column(
        "user_id",
        db.UUID(as_uuid=True),
        db.ForeignKey("vbwd_user.id"),
        primary_key=True,
    ),
    db.Column(
        "user_access_level_id",
        db.UUID(as_uuid=True),
        db.ForeignKey("vbwd_access_level.id"),
        primary_key=True,
    ),
)


class AccessLevel(BaseModel):
    """
    Access level — controls fe-user feature visibility.

    Unlike admin roles (vbwd_admin_role), these apply to
    regular users in the user-facing app. Plans auto-assign
    default levels via the subscription plugin.
    """

    __tablename__ = "vbwd_access_level"

    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.String(500))
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    linked_plan_slug = db.Column(db.String(100), nullable=True, index=True)

    # Many-to-many: level <-> permissions
    permissions = db.relationship(
        "Permission",
        secondary=user_access_level_permissions,
        backref=db.backref("user_access_levels", lazy="dynamic"),
        lazy="joined",
    )

    # Many-to-many: user <-> level
    users = db.relationship(
        "User",
        secondary=user_user_access_levels,
        backref=db.backref("assigned_user_access_levels", lazy="joined"),
        lazy="dynamic",
    )

    def has_permission(self, permission_name: str) -> bool:
        """Check if level grants a permission. Supports wildcards."""
        for perm in list(self.permissions):
            if perm.name == "*":
                return True
            if perm.name == permission_name:
                return True
            if perm.name.endswith(".*") and permission_name.startswith(perm.name[:-1]):
                return True
        return False

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "is_system": self.is_system,
            "linked_plan_slug": self.linked_plan_slug,
            "permissions": [p.name for p in list(self.permissions)],
        }

    def __repr__(self) -> str:
        return f"<AccessLevel(slug='{self.slug}')>"


# Transitional alias (S94 Slice 6a / DC-3): plugins still import
# ``UserAccessLevel`` — the alias keeps them working without code edits while
# core migrates to the unambiguous ``AccessLevel`` name.
UserAccessLevel = AccessLevel

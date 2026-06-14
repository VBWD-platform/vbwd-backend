"""User Group model (S73) — a first-class, hierarchical, multilingual grouping
of users.

A user may belong to 0..N groups. Membership is stored slug-keyed in the
``vbwd_user_group_rel`` M2M table (the slug is unique, so it is a valid FK
target and keeps import/export portable across instances). ``parent_group``
references another group's ``slug`` for a display/grouping hierarchy (no
permission inheritance in this sprint).

Like ``UserAccessLevel`` / ``Role``, this is a CORE entity. Plugins must never
import it — the subscription plugin reaches membership only through the
``IUserGroupMembership`` write port.
"""
from vbwd.extensions import db
from vbwd.models.base import BaseModel

# Association: user <-> user_group, keyed by the group's slug (S73). Both sides
# cascade on delete: removing a user OR a group prunes its membership rows.
user_group_rel = db.Table(
    "vbwd_user_group_rel",
    db.Column(
        "user_id",
        db.UUID(as_uuid=True),
        db.ForeignKey("vbwd_user.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "group_slug",
        db.String(100),
        db.ForeignKey("vbwd_user_groups.slug", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class UserGroup(BaseModel):
    """A named, hierarchical, multilingual group of users."""

    __tablename__ = "vbwd_user_groups"

    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    lang = db.Column(db.String(8), nullable=True)
    # Slug of the parent group (self-referential by slug, nullable for roots).
    parent_group = db.Column(db.String(100), nullable=True)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "slug": self.slug,
            "name": self.name,
            "lang": self.lang,
            "parent_group": self.parent_group,
            "created_at": (self.created_at.isoformat() if self.created_at else None),
            "updated_at": (self.updated_at.isoformat() if self.updated_at else None),
        }

    def __repr__(self) -> str:
        return f"<UserGroup(slug='{self.slug}')>"

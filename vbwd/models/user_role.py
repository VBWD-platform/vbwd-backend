"""Role lookup table backing the ``vbwd_user.role`` foreign key.

The canonical list of role slugs stays the ``UserRole`` enum in
``vbwd.models.enums`` (single source of truth). This module turns that enum
into a real reference table — ``vbwd_user_role`` — so the ``role`` column can
be a plain ``VARCHAR`` foreign key with database-level referential integrity,
instead of a native Postgres ``ENUM`` type.

NOTE on the table name: the RBAC subsystem already owns the *plural*
``vbwd_user_roles`` table — that is the user-to-RBAC-role many-to-many JOIN
(``vbwd.models.role.user_roles``), an entirely different concept. This lookup
of canonical ``UserRole`` values is therefore the *singular* ``vbwd_user_role``
to avoid colliding with that long-lived join table and its data/migrations.

The model is named ``RoleDefinition`` to avoid colliding with the ``UserRole``
*enum* (which remains the parse/comparison vocabulary the application uses).
``RoleDefinition`` is the *persisted row* describing one role.

It deliberately does NOT extend ``BaseModel``: ``BaseModel`` mandates a UUID
primary key, but this table's primary key is the capitalised slug string
(exactly the enum value), which is what the FK targets. It is therefore a
standalone ``db.Model`` with just ``id`` + ``name``.

Seeding lives in two places that share this module's single
``canonical_role_rows()`` source:
  * the Alembic migration (prod / migrated databases), and
  * the ``after_create`` DDL event below (every ``metadata.create_all()``
    path — dev bootstrap and the integration-test schema builder), which keeps
    the six rows present so any ``User`` insert satisfies the FK.
"""
from sqlalchemy import event, insert

from vbwd.extensions import db
from vbwd.models.enums import UserRole

# Column widths reused by both the model and the migration. The slug column is
# the primary key AND the FK target, so its width must match ``vbwd_user.role``.
ROLE_ID_LENGTH = 32
ROLE_NAME_LENGTH = 64


def human_readable_role_name(role: UserRole) -> str:
    """Title-case a role slug into a display name (``SUPER_ADMIN`` -> ``Super Admin``)."""
    return " ".join(part.capitalize() for part in role.value.split("_"))


def canonical_role_rows() -> list[dict]:
    """The six canonical rows, derived from the ``UserRole`` enum (DRY).

    A single source for the migration seed and the ``after_create`` seed, so
    the role list never drifts between the two paths.
    """
    return [
        {"id": role.value, "name": human_readable_role_name(role)} for role in UserRole
    ]


class RoleDefinition(db.Model):  # type: ignore[name-defined]
    """A persisted role row backing the ``vbwd_user.role`` foreign key."""

    __tablename__ = "vbwd_user_role"

    id = db.Column(db.String(ROLE_ID_LENGTH), primary_key=True)
    name = db.Column(db.String(ROLE_NAME_LENGTH), nullable=False)

    def to_dict(self) -> dict:
        """Serialise to ``{id, name}``."""
        return {"id": self.id, "name": self.name}

    def __repr__(self) -> str:
        return f"<RoleDefinition {self.id}>"


@event.listens_for(RoleDefinition.__table__, "after_create")
def _seed_canonical_roles(target, connection, **kwargs) -> None:
    """Seed the six canonical roles whenever the table is created via DDL.

    Fires for every ``metadata.create_all()`` (dev bootstrap, the integration
    test schema builder), so a freshly created schema always has the rows the
    ``vbwd_user.role`` FK requires. Idempotent by construction: the event only
    fires on CREATE TABLE, when the table is necessarily empty.
    """
    connection.execute(insert(RoleDefinition.__table__), canonical_role_rows())

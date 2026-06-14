"""Unit coverage for the ``RoleDefinition`` lookup model (role table).

Pure logic — no database. Verifies the canonical rows are derived from the
``UserRole`` enum (single source of truth), the display-name formatting, and
that the ``User.role`` column is now a varchar FK rather than a native enum.
"""
from sqlalchemy.types import Enum as SQLAlchemyEnum

from vbwd.models.enums import UserRole
from vbwd.models.user import User
from vbwd.models.user_role import (
    ROLE_ID_LENGTH,
    RoleDefinition,
    canonical_role_rows,
    human_readable_role_name,
)


def test_canonical_rows_cover_every_enum_member_exactly():
    rows = canonical_role_rows()
    assert {row["id"] for row in rows} == {member.value for member in UserRole}
    assert len(rows) == len(list(UserRole)) == 6


def test_human_readable_names_are_title_cased():
    assert human_readable_role_name(UserRole.SUPER_ADMIN) == "Super Admin"
    assert human_readable_role_name(UserRole.ADMIN) == "Admin"
    assert human_readable_role_name(UserRole.USER) == "User"
    assert human_readable_role_name(UserRole.VENDOR) == "Vendor"
    assert human_readable_role_name(UserRole.BOT) == "Bot"
    assert human_readable_role_name(UserRole.GUEST) == "Guest"


def test_role_id_is_the_capitalised_slug():
    by_id = {row["id"]: row["name"] for row in canonical_role_rows()}
    assert by_id["SUPER_ADMIN"] == "Super Admin"
    assert by_id["GUEST"] == "Guest"


def test_to_dict_returns_id_and_name():
    definition = RoleDefinition(id="ADMIN", name="Admin")
    assert definition.to_dict() == {"id": "ADMIN", "name": "Admin"}


def test_role_definition_table_name_and_string_pk():
    assert RoleDefinition.__tablename__ == "vbwd_user_role"
    assert RoleDefinition.__table__.c.id.primary_key is True
    assert RoleDefinition.__table__.c.id.type.length == ROLE_ID_LENGTH


def test_user_role_column_is_varchar_fk_not_native_enum():
    role_column = User.__table__.c.role
    assert isinstance(role_column.type, SQLAlchemyEnum)
    # native_enum=False => no Postgres ENUM type is created.
    assert role_column.type.native_enum is False
    # FK targets the new lookup table.
    fk_targets = {fk.target_fullname for fk in role_column.foreign_keys}
    assert "vbwd_user_role.id" in fk_targets

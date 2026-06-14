"""Integration coverage for the ``vbwd_user_role`` lookup table.

Exercises the *create_all path* end-to-end against a throwaway PostgreSQL
database (so it never touches the shared ``vbwd`` test DB):

  * after ``metadata.create_all()`` the lookup table holds exactly the six
    canonical rows (seeded by the ``after_create`` DDL event),
  * a ``User`` persists with ``role=UserRole.ADMIN``, reads back as the
    ``UserRole.ADMIN`` enum member, and the stored column value is the FK
    string ``"ADMIN"``,
  * inserting a user with a role string absent from the lookup table is
    rejected by the foreign-key constraint.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from vbwd.app import create_app
from vbwd.extensions import db
from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User


def _admin_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, _ = base.rpartition("/")
    return f"{prefix}/postgres"


@pytest.fixture
def role_table_app():
    """A Flask app bound to a fresh throwaway DB with the full schema built
    via ``create_all`` (the seam the ``after_create`` role seed must cover)."""
    admin_url = _admin_url()
    db_name = f"role_table_{uuid.uuid4().hex[:10]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    target_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"

    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": target_url,
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "RATELIMIT_ENABLED": False,
        }
    )
    with app.app_context():
        db.create_all()
        try:
            yield app
        finally:
            db.session.remove()
            db.engine.dispose()

    with admin_engine.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :n AND pid <> pg_backend_pid()"
            ),
            {"n": db_name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    admin_engine.dispose()


def test_create_all_seeds_exactly_the_six_canonical_roles(role_table_app):
    rows = db.session.execute(
        text("SELECT id, name FROM vbwd_user_role ORDER BY id")
    ).fetchall()
    by_id = {row[0]: row[1] for row in rows}
    assert by_id == {
        "ADMIN": "Admin",
        "BOT": "Bot",
        "GUEST": "Guest",
        "SUPER_ADMIN": "Super Admin",
        "USER": "User",
        "VENDOR": "Vendor",
    }


def test_user_role_round_trips_as_enum_with_fk_string_stored(role_table_app):
    user = User(
        email="admin-role@example.com",
        password_hash="x",
        status=UserStatus.ACTIVE,
        role=UserRole.ADMIN,
    )
    db.session.add(user)
    db.session.commit()
    user_id = user.id
    db.session.expire_all()

    reloaded = db.session.get(User, user_id)
    # Enum identity preserved through the ORM.
    assert reloaded.role is UserRole.ADMIN
    assert reloaded.role == UserRole.ADMIN
    assert reloaded.is_admin is True

    # The raw column value is the FK slug string.
    raw_value = db.session.execute(
        text("SELECT role FROM vbwd_user WHERE id = :id"), {"id": str(user_id)}
    ).scalar()
    assert raw_value == "ADMIN"


def test_unknown_role_string_violates_foreign_key(role_table_app):
    with pytest.raises(IntegrityError):
        db.session.execute(
            text(
                "INSERT INTO vbwd_user "
                "(id, email, password_hash, status, role, has_used_trial, "
                " version, created_at, updated_at) "
                "VALUES (:id, :email, 'x', 'ACTIVE', 'NOT_A_ROLE', false, "
                " 0, now(), now())"
            ),
            {"id": str(uuid.uuid4()), "email": "bad-role@example.com"},
        )
        db.session.commit()
    db.session.rollback()

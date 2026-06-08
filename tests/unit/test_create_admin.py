"""Unit tests for bin/create_admin.py — Sprint S38.

create_admin must assign the granular ``super_admin`` role (via RBACService)
AND keep setting the coarse ``UserRole.SUPER_ADMIN`` enum, and must seed the
default roles first when they are absent so a fresh box self-heals.

Uses the live test DB (the seeder + RBACService need real commit semantics),
isolating by a unique email + wiping RBAC tables around each test.
"""
import importlib.util
import os
from uuid import uuid4

import pytest

from vbwd.extensions import db
from vbwd.models.role import Role, Permission, role_permissions, user_roles
from vbwd.models.user_access_level import user_access_level_permissions
from vbwd.models.user import User
from vbwd.models.enums import UserRole, UserStatus
from vbwd.repositories.role_repository import RoleRepository


_CREATE_ADMIN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..",
    "bin",
    "create_admin.py",
)


def _load_create_admin():
    spec = importlib.util.spec_from_file_location(
        "create_admin_under_test", os.path.abspath(_CREATE_ADMIN_PATH)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wipe_rbac(session):
    # Clear the user↔role link first (see test_rbac_seeder._wipe_rbac): an
    # admin-with-role seeded at app startup otherwise makes DELETE FROM
    # vbwd_role violate vbwd_user_roles_role_id_fkey.
    session.execute(user_roles.delete())
    session.execute(role_permissions.delete())
    session.execute(user_access_level_permissions.delete())
    session.query(Role).delete()
    session.query(Permission).delete()
    session.commit()


@pytest.fixture
def module():
    return _load_create_admin()


@pytest.fixture
def session(app):
    with app.app_context():
        _wipe_rbac(db.session)
        created_emails = []
        yield db.session, created_emails
        db.session.rollback()
        for email in created_emails:
            user = db.session.query(User).filter_by(email=email).first()
            if user:
                db.session.delete(user)
        db.session.commit()
        _wipe_rbac(db.session)


class TestCreateOrPromoteAdmin:
    def test_assigns_super_admin_role_and_keeps_enum(self, module, session):
        db_session, created_emails = session
        email = f"admin-{uuid4().hex[:8]}@example.com"
        created_emails.append(email)

        user = module.create_or_promote_admin(
            db_session, email, "Secret123!", plugin_manager=None
        )

        assert user.role == UserRole.SUPER_ADMIN
        assert user.status == UserStatus.ACTIVE

        role_repo = RoleRepository(db_session)
        assert role_repo.user_has_role(user.id, "super_admin")

    def test_seeds_roles_when_absent(self, module, session):
        db_session, created_emails = session
        assert db_session.query(Role).count() == 0

        email = f"admin-{uuid4().hex[:8]}@example.com"
        created_emails.append(email)
        module.create_or_promote_admin(
            db_session, email, "Secret123!", plugin_manager=None
        )

        slugs = {r.slug for r in db_session.query(Role).all()}
        assert {"super_admin", "admin"}.issubset(slugs)

    def test_promotes_existing_user(self, module, session):
        db_session, created_emails = session
        email = f"admin-{uuid4().hex[:8]}@example.com"
        created_emails.append(email)

        existing = User(
            email=email,
            password_hash="x",
            status=UserStatus.PENDING,
            role=UserRole.USER,
        )
        db_session.add(existing)
        db_session.commit()

        user = module.create_or_promote_admin(
            db_session, email, "Secret123!", plugin_manager=None
        )

        assert user.role == UserRole.SUPER_ADMIN
        assert user.status == UserStatus.ACTIVE

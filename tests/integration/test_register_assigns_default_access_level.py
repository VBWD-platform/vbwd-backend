"""Integration: a user registered through ``AuthService`` receives the core
``logged-in`` user access level, so ``effective_user_permissions`` is populated
and the fe-user router's permission guards resolve (instead of bouncing every
guarded route to /dashboard).

Runs against the real integration Postgres. RBAC is seeded through the real
``seed_default_rbac`` service (create-only / idempotent), never raw SQL, and the
user created by the test is removed at the end so re-runs stay clean.
"""
import uuid

import pytest


@pytest.fixture
def app():
    """Real app against the integration Postgres DB."""
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": get_database_url(),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "RATELIMIT_ENABLED": False,
    }
    return create_app(test_config)


def test_registered_user_gets_logged_in_level_and_permissions(app):
    from vbwd.extensions import db
    from vbwd.repositories.user_repository import UserRepository
    from vbwd.services.auth_service import (
        AuthService,
        DEFAULT_USER_ACCESS_LEVEL_SLUG,
    )
    from vbwd.services.rbac_seeder import seed_default_rbac
    from vbwd.services.user_access_level_service import UserAccessLevelService

    with app.app_context():
        # Seed the permission catalog + default access levels (idempotent).
        seed_default_rbac(db.session, plugin_manager=app.plugin_manager)
        db.session.commit()

        user_repo = UserRepository(db.session)
        auth_service = AuthService(
            user_repository=user_repo,
            access_level_service=UserAccessLevelService(db.session),
        )

        email = f"defaultlevel-{uuid.uuid4().hex}@example.com"
        created_user_id = None
        try:
            result = auth_service.register(email, "SecurePassword123!")
            assert result.success is True, result.error
            created_user_id = result.user_id

            # Prove persistence across a session refresh, not just a pending flush.
            db.session.expire_all()
            user = user_repo.find_by_id(created_user_id)
            assert user is not None

            assigned_slugs = {level.slug for level in user.assigned_user_access_levels}
            assert DEFAULT_USER_ACCESS_LEVEL_SLUG in assigned_slugs

            permissions = set(user.effective_user_permissions)
            assert "user.profile.view" in permissions
            assert "subscription.invoices.view" in permissions
            assert "subscription.tokens.view" in permissions
        finally:
            if created_user_id is not None:
                access_level_service = UserAccessLevelService(db.session)
                for level in access_level_service.get_user_levels(created_user_id):
                    access_level_service.revoke(created_user_id, level.id)
                db.session.commit()
                user_repo.delete(created_user_id)
                db.session.commit()

"""Integration (S152 C3): ``GET /api/v1/user/profile`` carries the user's access
levels and user permissions with exactly the login response's shape and values.

Runs against the real integration Postgres through the real app + test client.
RBAC is seeded through ``seed_default_rbac`` (create-only), users are created
through ``AuthService.register`` and their levels/roles changed through core
services/repositories — never raw SQL. Every user is removed afterwards.
"""
import uuid

import pytest

from vbwd.models.enums import UserRole

TEST_PASSWORD = "SecurePassword123!"
ALL_USER_PERMISSIONS = ["*"]


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


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user(app):
    """Register a user (gets the default level), optionally strip levels / set role."""
    from vbwd.extensions import db
    from vbwd.repositories.user_repository import UserRepository
    from vbwd.services.auth_service import AuthService
    from vbwd.services.rbac_seeder import seed_default_rbac
    from vbwd.services.user_access_level_service import UserAccessLevelService

    created_user_ids = []
    with app.app_context():
        seed_default_rbac(db.session, plugin_manager=app.plugin_manager)
        db.session.commit()

        def _make_user(role=UserRole.USER, keep_access_levels=True):
            user_repository = UserRepository(db.session)
            access_level_service = UserAccessLevelService(db.session)
            auth_service = AuthService(
                user_repository=user_repository,
                access_level_service=access_level_service,
            )
            email = f"profile-levels-{uuid.uuid4().hex}@example.com"
            result = auth_service.register(email, TEST_PASSWORD)
            assert result.success is True, result.error
            created_user_ids.append(result.user_id)
            if not keep_access_levels:
                for level in access_level_service.get_user_levels(result.user_id):
                    access_level_service.revoke(result.user_id, level.id)
            user = user_repository.find_by_id(result.user_id)
            user.role = role
            user_repository.save(user)
            db.session.commit()
            return email

        yield _make_user

        access_level_service = UserAccessLevelService(db.session)
        user_repository = UserRepository(db.session)
        for user_id in created_user_ids:
            for level in access_level_service.get_user_levels(user_id):
                access_level_service.revoke(user_id, level.id)
            db.session.commit()
            user_repository.delete(user_id)


def _login_and_profile(client, email):
    login_response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD}
    )
    assert login_response.status_code == 200, login_response.get_json()
    login_body = login_response.get_json()
    profile_response = client.get(
        "/api/v1/user/profile",
        headers={"Authorization": f"Bearer {login_body['token']}"},
    )
    assert profile_response.status_code == 200, profile_response.get_json()
    return login_body["user"], profile_response.get_json()["user"]


def _assert_profile_matches_login(login_user, profile_user):
    assert profile_user["id"] == login_user["id"]
    assert profile_user["user_access_levels"] == login_user["user_access_levels"]
    assert profile_user["user_permissions"] == login_user["user_permissions"]


def test_user_with_level_gets_login_levels_and_permissions(client, make_user):
    from vbwd.services.auth_service import DEFAULT_USER_ACCESS_LEVEL_SLUG

    login_user, profile_user = _login_and_profile(client, make_user())

    _assert_profile_matches_login(login_user, profile_user)
    assert [level["slug"] for level in profile_user["user_access_levels"]] == [
        DEFAULT_USER_ACCESS_LEVEL_SLUG
    ]
    level = profile_user["user_access_levels"][0]
    assert set(level.keys()) == {"id", "slug", "name"}
    uuid.UUID(level["id"])
    assert "user.profile.view" in profile_user["user_permissions"]


def test_user_without_levels_gets_empty_lists(client, make_user):
    login_user, profile_user = _login_and_profile(
        client, make_user(keep_access_levels=False)
    )

    _assert_profile_matches_login(login_user, profile_user)
    assert profile_user["user_access_levels"] == []
    assert profile_user["user_permissions"] == []


def test_super_admin_holds_every_user_permission(client, make_user):
    login_user, profile_user = _login_and_profile(
        client, make_user(role=UserRole.SUPER_ADMIN)
    )

    _assert_profile_matches_login(login_user, profile_user)
    assert profile_user["user_permissions"] == ALL_USER_PERMISSIONS


def test_admin_without_levels_holds_every_user_permission(client, make_user):
    login_user, profile_user = _login_and_profile(
        client, make_user(role=UserRole.ADMIN, keep_access_levels=False)
    )

    _assert_profile_matches_login(login_user, profile_user)
    assert profile_user["user_access_levels"] == []
    assert profile_user["user_permissions"] == ALL_USER_PERMISSIONS


def test_admin_with_levels_holds_only_the_level_permissions(client, make_user):
    login_user, profile_user = _login_and_profile(
        client, make_user(role=UserRole.ADMIN)
    )

    _assert_profile_matches_login(login_user, profile_user)
    assert profile_user["user_permissions"] != ALL_USER_PERMISSIONS
    assert "user.profile.view" in profile_user["user_permissions"]


def test_profile_user_is_its_existing_keys_plus_levels_and_permissions(
    client, make_user
):
    _, profile_user = _login_and_profile(client, make_user())

    assert set(profile_user.keys()) == {
        "id",
        "email",
        "status",
        "role",
        "created_at",
        "updated_at",
        "user_access_levels",
        "user_permissions",
    }

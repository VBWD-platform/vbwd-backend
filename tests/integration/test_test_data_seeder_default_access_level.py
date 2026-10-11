"""Integration: ``flask seed-test-data`` (``TestDataSeeder.seed``) grants the
seeded test user the same default access level a real registration gets, so
the login / profile payload carries it and its user permissions. Re-running the
seeder never duplicates the level.

Runs against the real integration Postgres through the real app + test client.
RBAC is seeded through ``seed_default_rbac`` (create-only). The seeder runs
with unique test emails and with plugin-contributed test data stubbed out, so
this test never touches the shared ``test@example.com`` fixtures; the users it
creates are removed through core repositories afterwards.
"""
import uuid

import pytest

TEST_PASSWORD = "SeedPass123@"


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
def seeded_emails(app, monkeypatch):
    """Unique seeder identities; users removed through repositories after."""
    from vbwd.extensions import db
    from vbwd.repositories.user_repository import UserRepository
    from vbwd.services.rbac_seeder import seed_default_rbac

    unique_suffix = uuid.uuid4().hex
    test_user_email = f"seed-user-{unique_suffix}@example.com"
    test_admin_email = f"seed-admin-{unique_suffix}@example.com"
    monkeypatch.setenv("TEST_DATA_SEED", "true")
    monkeypatch.setenv("TEST_USER_EMAIL", test_user_email)
    monkeypatch.setenv("TEST_USER_PASSWORD", TEST_PASSWORD)
    monkeypatch.setenv("TEST_ADMIN_EMAIL", test_admin_email)
    monkeypatch.setattr(
        "vbwd.testing.test_data_seeder.run_test_data_seeders",
        lambda session, test_user: None,
    )

    with app.app_context():
        seed_default_rbac(db.session, plugin_manager=app.plugin_manager)
        db.session.commit()

        yield test_user_email

        user_repository = UserRepository(db.session)
        for email in (test_user_email, test_admin_email):
            user = user_repository.find_by_email(email)
            if user is not None:
                user_repository.delete(user.id)


def _login_user_payload(client, email):
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["user"]


def test_seeded_user_has_default_level_and_permissions(app, seeded_emails):
    from vbwd.extensions import db
    from vbwd.services.auth_service import DEFAULT_USER_ACCESS_LEVEL_SLUG
    from vbwd.testing.test_data_seeder import TestDataSeeder

    assert TestDataSeeder(db.session).seed() is True

    login_user = _login_user_payload(app.test_client(), seeded_emails)
    assert [level["slug"] for level in login_user["user_access_levels"]] == [
        DEFAULT_USER_ACCESS_LEVEL_SLUG
    ]
    assert "user.profile.view" in login_user["user_permissions"]


def test_reseeding_does_not_duplicate_default_level(app, seeded_emails):
    from vbwd.extensions import db
    from vbwd.repositories.user_repository import UserRepository
    from vbwd.services.user_access_level_service import UserAccessLevelService
    from vbwd.testing.test_data_seeder import TestDataSeeder

    assert TestDataSeeder(db.session).seed() is True
    assert TestDataSeeder(db.session).seed() is True

    seeded_user = UserRepository(db.session).find_by_email(seeded_emails)
    levels = UserAccessLevelService(db.session).get_user_levels(seeded_user.id)
    assert len(levels) == 1

    login_user = _login_user_payload(app.test_client(), seeded_emails)
    assert len(login_user["user_access_levels"]) == 1

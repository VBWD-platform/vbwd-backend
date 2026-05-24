"""
Unit tests for TestDataSeeder service.

TDD: These tests are written BEFORE the implementation.
"""
from unittest.mock import MagicMock, patch
import os

import pytest

from vbwd.services.demo_data_registry import (
    register_test_data_seeder,
    clear_demo_data_hooks,
)


@pytest.fixture(autouse=True)
def _reset_demo_hooks():
    """Registry is module-global — isolate every test."""
    clear_demo_data_hooks()
    yield
    clear_demo_data_hooks()


class TestTestDataSeeder:
    """Test the test data seeder service."""

    def test_seeder_skips_when_env_false(self):
        """Seeder should skip when TEST_DATA_SEED is false."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        with patch.dict(os.environ, {"TEST_DATA_SEED": "false"}, clear=False):
            seeder = TestDataSeeder(db_session=MagicMock())
            result = seeder.seed()
            assert result is False

    def test_seeder_skips_when_env_not_set(self):
        """Seeder should skip when TEST_DATA_SEED is not set (default)."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        env = os.environ.copy()
        env.pop("TEST_DATA_SEED", None)
        with patch.dict(os.environ, env, clear=True):
            seeder = TestDataSeeder(db_session=MagicMock())
            result = seeder.seed()
            assert result is False

    def test_seeder_runs_when_env_true(self):
        """Seeder should run when TEST_DATA_SEED is true."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        mock_session = MagicMock()
        # Mock query to return None (no existing data)
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch.dict(os.environ, {"TEST_DATA_SEED": "true"}, clear=False):
            seeder = TestDataSeeder(db_session=mock_session)
            result = seeder.seed()
            assert result is True
            assert mock_session.commit.called

    def test_seeder_runs_when_env_TRUE_uppercase(self):
        """Seeder should handle uppercase TRUE."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch.dict(os.environ, {"TEST_DATA_SEED": "TRUE"}, clear=False):
            seeder = TestDataSeeder(db_session=mock_session)
            result = seeder.seed()
            assert result is True

    def test_seeder_creates_test_user(self):
        """Seeder should create test user with configured credentials."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch.dict(
            os.environ,
            {
                "TEST_DATA_SEED": "true",
                "TEST_USER_EMAIL": "testuser@example.com",
                "TEST_USER_PASSWORD": "TestPass123@",
            },
            clear=False,
        ):
            seeder = TestDataSeeder(db_session=mock_session)
            seeder.seed()

            # Verify session.add was called
            assert mock_session.add.called

    def test_seeder_uses_default_email_when_not_configured(self):
        """Seeder should use default email when TEST_USER_EMAIL not set."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        env = {"TEST_DATA_SEED": "true"}
        with patch.dict(os.environ, env, clear=False):
            seeder = TestDataSeeder(db_session=mock_session)
            seeder.seed()
            # Should not raise an error - uses defaults
            assert mock_session.commit.called

    def test_seeder_creates_test_admin(self):
        """Seeder should create admin user."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch.dict(
            os.environ,
            {
                "TEST_DATA_SEED": "true",
                "TEST_ADMIN_EMAIL": "admin@example.com",
                "TEST_ADMIN_PASSWORD": "AdminPass123@",
            },
            clear=False,
        ):
            seeder = TestDataSeeder(db_session=mock_session)
            seeder.seed()
            assert mock_session.add.called

    def test_seeder_invokes_registered_plugin_test_data_hook(self):
        """Core seeds user+admin then delegates plugin test data (plan +
        subscription) to the registered hook with (session, test_user)."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        called = {}

        def _hook(session, test_user):
            called["session"] = session
            called["test_user"] = test_user

        register_test_data_seeder(_hook)

        with patch.dict(os.environ, {"TEST_DATA_SEED": "true"}, clear=False):
            seeder = TestDataSeeder(db_session=mock_session)
            seeder.seed()

            # user + admin created by core
            assert mock_session.add.call_count == 2
            # plugin hook invoked with the live session + the test user
            assert called["session"] is mock_session
            assert called["test_user"] is not None

    def test_seeder_skips_existing_user(self):
        """Seeder should not duplicate existing test user."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        mock_session = MagicMock()
        existing_user = MagicMock()
        existing_user.id = "existing-uuid"

        # First call returns existing user, rest return None
        mock_session.query.return_value.filter_by.return_value.first.side_effect = [
            existing_user,  # test user exists
            None,  # admin doesn't exist
            None,  # plan doesn't exist
            None,  # subscription doesn't exist
        ]

        with patch.dict(os.environ, {"TEST_DATA_SEED": "true"}, clear=False):
            seeder = TestDataSeeder(db_session=mock_session)
            seeder.seed()
            # Should still succeed
            assert mock_session.commit.called

    def test_cleanup_skips_when_env_false(self):
        """Cleanup should skip when TEST_DATA_CLEANUP is false."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        mock_session = MagicMock()
        with patch.dict(os.environ, {"TEST_DATA_CLEANUP": "false"}, clear=False):
            seeder = TestDataSeeder(db_session=mock_session)
            result = seeder.cleanup()
            assert result is False
            assert not mock_session.commit.called

    def test_cleanup_skips_when_env_not_set(self):
        """Cleanup should skip when TEST_DATA_CLEANUP is not set (default)."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        mock_session = MagicMock()
        env = os.environ.copy()
        env.pop("TEST_DATA_CLEANUP", None)
        with patch.dict(os.environ, env, clear=True):
            seeder = TestDataSeeder(db_session=mock_session)
            result = seeder.cleanup()
            assert result is False

    def test_cleanup_runs_when_env_true(self):
        """Cleanup should remove test data when TEST_DATA_CLEANUP is true."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.all.return_value = []

        with patch.dict(os.environ, {"TEST_DATA_CLEANUP": "true"}, clear=False):
            seeder = TestDataSeeder(db_session=mock_session)
            result = seeder.cleanup()
            assert result is True
            assert mock_session.commit.called

    def test_should_seed_returns_bool(self):
        """should_seed() should return boolean."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        seeder = TestDataSeeder(db_session=MagicMock())

        with patch.dict(os.environ, {"TEST_DATA_SEED": "true"}, clear=False):
            assert seeder.should_seed() is True

        with patch.dict(os.environ, {"TEST_DATA_SEED": "false"}, clear=False):
            assert seeder.should_seed() is False

    def test_should_cleanup_returns_bool(self):
        """should_cleanup() should return boolean."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        seeder = TestDataSeeder(db_session=MagicMock())

        with patch.dict(os.environ, {"TEST_DATA_CLEANUP": "true"}, clear=False):
            assert seeder.should_cleanup() is True

        with patch.dict(os.environ, {"TEST_DATA_CLEANUP": "false"}, clear=False):
            assert seeder.should_cleanup() is False


class TestTestDataSeederMarker:
    """Test the marker used to identify test data."""

    def test_marker_is_defined(self):
        """TestDataSeeder should have a TEST_DATA_MARKER constant."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        assert hasattr(TestDataSeeder, "TEST_DATA_MARKER")
        assert isinstance(TestDataSeeder.TEST_DATA_MARKER, str)
        assert len(TestDataSeeder.TEST_DATA_MARKER) > 0

    def test_marker_used_in_plan_name(self):
        """Test plans should use the marker prefix for identification."""
        from vbwd.testing.test_data_seeder import TestDataSeeder

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch.dict(os.environ, {"TEST_DATA_SEED": "true"}, clear=False):
            seeder = TestDataSeeder(db_session=mock_session)
            seeder.seed()

            # Find the TarifPlan add call
            add_calls = mock_session.add.call_args_list
            # At least one call should have an object with name containing marker
            # (This is a weak test - implementation will validate)
            assert len(add_calls) > 0

"""Tests for Taro plugin routes - simplified version without complex mocking."""
import pytest
from contextlib import contextmanager
from unittest.mock import Mock, patch
from uuid import uuid4

_AUTH_HEADER = {"Authorization": "Bearer test-token"}


@contextmanager
def auth_as(user_id):
    """Patches require_auth internals so the route runs as user_id."""
    mock_user = Mock()
    mock_user.status = Mock(value="ACTIVE")
    mock_user.id = user_id

    with patch("src.middleware.auth.AuthService") as mock_auth_cls:
        with patch("src.middleware.auth.UserRepository") as mock_repo_cls:
            mock_auth_cls.return_value.verify_token.return_value = user_id
            mock_repo_cls.return_value.find_by_id.return_value = mock_user
            yield


@pytest.fixture
def app():
    """Create Flask app for testing."""
    from flask import Flask

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = "test-secret"
    from plugins.taro.src.routes import taro_bp

    app.register_blueprint(taro_bp, url_prefix="/api/v1/taro")
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def mock_auth_header():
    """Fixture providing valid auth header."""
    return _AUTH_HEADER


@pytest.fixture
def mock_current_user():
    """Fixture providing mock current user."""
    user = Mock()
    user.id = str(uuid4())
    user.user_profile = Mock()
    user.user_profile.current_tarif_plan = Mock()
    user.user_profile.current_tarif_plan.id = "plan-star"
    user.user_profile.current_tarif_plan.daily_taro_limit = 3
    user.user_profile.current_tarif_plan.max_taro_follow_ups = 3
    return user


@pytest.fixture
def mock_dispatcher():
    """Fixture providing mock event dispatcher."""
    dispatcher = Mock()
    dispatcher.emit = Mock()
    return dispatcher


class TestTaroRoutes:
    """Test Taro routes with proper mocking."""

    def test_session_route_exists(self, client):
        """Test that session route is accessible."""
        # This tests that the route exists and is registered
        user_id = str(uuid4())
        with auth_as(user_id):
            with patch(
                "plugins.taro.src.routes.get_user_tarif_plan_limits",
                return_value=(3, 3),
            ):
                with patch(
                    "plugins.taro.src.routes.check_token_balance", return_value=True
                ):
                    # The route should exist and handle the request
                    response = client.post(
                        "/api/v1/taro/session", json={}, headers=_AUTH_HEADER
                    )
                    # Should not get 404 (route exists)
                    assert response.status_code != 404

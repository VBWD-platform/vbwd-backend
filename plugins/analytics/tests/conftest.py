"""Test fixtures for analytics plugin tests."""
import pytest
import os

os.environ["FLASK_ENV"] = "testing"
os.environ["TESTING"] = "true"


@pytest.fixture
def app():
    """Create application for testing."""
    from src.app import create_app
    from src.config import get_database_url

    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": get_database_url(),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "RATELIMIT_ENABLED": True,
        "RATELIMIT_STORAGE_URL": "memory://",
    }

    app = create_app(test_config)

    from src.extensions import limiter

    limiter.reset()

    yield app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()

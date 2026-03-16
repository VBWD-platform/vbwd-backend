"""Test fixtures for Taro plugin tests."""
import pytest
import os
import sys

# Add src and plugins to path for proper imports
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../src"))
)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

os.environ["FLASK_ENV"] = "testing"
os.environ["TESTING"] = "true"


def _test_db_url() -> str:
    """Derive a separate test DB URL to avoid destroying the API's schema.

    Unit tests call db.drop_all() for cleanup — using the same database as
    the running API would wipe all tables.  We append '_test' to the DB name
    so create_all / drop_all are scoped to a throw-away database.
    """
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    # Split on the last "/" to get the DB name; strip any query params
    prefix, _, dbname = base.rpartition("/")
    dbname = dbname.split("?")[0]
    return f"{prefix}/{dbname}_test"


def _ensure_test_db(url: str) -> None:
    """Create the test database if it does not exist."""
    from sqlalchemy import create_engine, text

    # Connect to the default 'postgres' maintenance DB to issue CREATE DATABASE
    main_url = url.rsplit("/", 1)[0] + "/postgres"
    dbname = url.rsplit("/", 1)[1].split("?")[0]
    engine = create_engine(main_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": dbname}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    finally:
        engine.dispose()


@pytest.fixture
def app():
    """Create application for testing against an isolated test database."""
    from src.app import create_app

    url = _test_db_url()
    _ensure_test_db(url)

    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": url,
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


@pytest.fixture
def db(app):
    """Provide database for testing.

    Creates all tables in the isolated test database, yields the db handle,
    then drops everything.  This never touches the main 'vbwd' database.
    """
    from src.extensions import db

    with app.app_context():
        db.create_all()
        yield db
        db.session.remove()
        db.drop_all()

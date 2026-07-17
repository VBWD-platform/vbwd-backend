"""Application configuration."""
import os
from typing import Any, Dict, Mapping, Optional, Type

# Constants - avoid magic numbers
DEFAULT_JWT_EXPIRATION_HOURS = 24
DEFAULT_SECRET_KEY = "dev-secret-key-change-in-production"

# --- S48.1: connection-pool / worker tuning ---------------------------------
#
# INVARIANT (enforced by tests/unit/test_connection_pool_tuning.py):
#
#     workers x (pool_size + max_overflow) + reserve <= Postgres max_connections
#
# Postgres ships with max_connections=200 (docker-compose.yaml). With the
# documented defaults below: 4 workers x (10 + 10) = 80, leaving ample reserve
# (~120) for migrations, the superuser, and admin tooling. Real horizontal
# scale is achieved with pgbouncer (S48.4), NOT by raising max_connections.
#
# All values are env-driven so prod (many cores, pgbouncer) and CI (2 cores)
# run identical code with different env.
DEFAULT_DB_POOL_SIZE = 10
DEFAULT_DB_MAX_OVERFLOW = 10
# A request waits at most this long for a free connection, then errors fast
# (mapped to a 503 by the app) instead of hanging the worker.
DEFAULT_DB_POOL_TIMEOUT_SECONDS = 5
# Recycle connections after an hour to drop ones the DB/proxy has closed.
DEFAULT_DB_POOL_RECYCLE_SECONDS = 3600
# The worker count the invariant is pinned against. The runtime default in
# gunicorn.conf.py is (2 x CPU) + 1; on the 2-core CI/dev box that is 5, but
# the documented guard uses 4 as the worst-case prod baseline this math must
# hold for.
DEFAULT_GUNICORN_WORKERS = 4


def build_engine_options(
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Build SQLAlchemy engine pool options from environment with safe defaults.

    Reads ``DB_POOL_SIZE`` / ``DB_MAX_OVERFLOW`` / ``DB_POOL_TIMEOUT`` and falls
    back to the documented safe defaults. ``pool_pre_ping`` and ``pool_recycle``
    are always present. Kept as a pure function (no global ``os.environ`` read
    baked in) so it is unit-testable and the single source of truth for both
    Flask-SQLAlchemy (``SQLALCHEMY_ENGINE_OPTIONS``) and the standalone engine
    in ``vbwd/extensions.py``.

    Args:
        env: Mapping to read overrides from; defaults to ``os.environ``.

    Returns:
        Dict of keyword arguments accepted by both ``create_engine`` and
        Flask-SQLAlchemy's ``SQLALCHEMY_ENGINE_OPTIONS``.
    """
    source = os.environ if env is None else env
    pool_size = int(source.get("DB_POOL_SIZE", DEFAULT_DB_POOL_SIZE))
    max_overflow = int(source.get("DB_MAX_OVERFLOW", DEFAULT_DB_MAX_OVERFLOW))
    pool_timeout = int(source.get("DB_POOL_TIMEOUT", DEFAULT_DB_POOL_TIMEOUT_SECONDS))
    pool_recycle = int(source.get("DB_POOL_RECYCLE", DEFAULT_DB_POOL_RECYCLE_SECONDS))
    return {
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": pool_timeout,
        "pool_pre_ping": True,
        "pool_recycle": pool_recycle,
    }


# Internationalization
AVAILABLE_LANGUAGES = [
    {"code": "en", "name": "English"},
    {"code": "de", "name": "Deutsch"},
    {"code": "ru", "name": "Русский"},
    {"code": "th", "name": "ไทย"},
    {"code": "zh", "name": "中文"},
    {"code": "es", "name": "Español"},
    {"code": "fr", "name": "Français"},
    {"code": "ja", "name": "日本語"},
]
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en")


def get_database_url() -> str:
    """Get PostgreSQL connection URL."""
    return os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")


def get_redis_url() -> str:
    """Get Redis connection URL."""
    return os.getenv("REDIS_URL", "redis://redis:6379/0")


# Database engine configuration for distributed systems (Sprint 1).
# Pool sizing comes from build_engine_options (S48.1) — env-driven, safe by
# default, and the single source of truth shared with vbwd/extensions.py.
_ENGINE_POOL_OPTIONS = build_engine_options()
DATABASE_CONFIG = {
    "url": get_database_url(),
    "isolation_level": "READ_COMMITTED",  # PostgreSQL default (explicit)
    **_ENGINE_POOL_OPTIONS,
}


class Config:
    """Base configuration."""

    # Flask
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", DEFAULT_SECRET_KEY)

    # Database
    SQLALCHEMY_DATABASE_URI = get_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = dict(_ENGINE_POOL_OPTIONS)

    # Redis
    REDIS_URL = get_redis_url()

    # Read-through catalogue cache (S48.2). Generic infra: enable flag + TTL
    # backstop. Disabled in tests so unit/integration runs are deterministic.
    CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() == "true"
    CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "120"))

    # Rate limiting. Default ON (prod enforces the per-route @limiter caps);
    # the local/integration-test API server sets RATELIMIT_ENABLED=false so the
    # many fixture logins don't trip the beta auth caps (S90 G5). Unit tests set
    # their own value via the app fixture's config dict.
    RATELIMIT_ENABLED = os.getenv("RATELIMIT_ENABLED", "true").lower() == "true"

    # Security
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", SECRET_KEY)
    JWT_EXPIRATION_HOURS = int(
        os.getenv("JWT_EXPIRATION_HOURS", DEFAULT_JWT_EXPIRATION_HOURS)
    )
    JWT_ACCESS_TOKEN_EXPIRES = JWT_EXPIRATION_HOURS * 3600  # Convert to seconds

    # Flask-JWT-Extended configuration
    JWT_TOKEN_LOCATION = ["headers"]
    JWT_HEADER_NAME = "Authorization"
    JWT_HEADER_TYPE = "Bearer"
    JWT_IDENTITY_CLAIM = "user_id"  # Match the claim name used in tokens

    # Celery
    CELERY_BROKER_URL = get_redis_url()
    CELERY_RESULT_BACKEND = get_redis_url()

    # License gate (S135-CLIENT) — ops-tunable, safe defaults. CE never enforces
    # (LICENSE_REQUIRED defaults false), so a clean git clone boots fully open;
    # the "gated"/ME builds turn it on. The public key is a build constant/config
    # value (the client verifies, never mints); grace_days is the fallback when a
    # key omits its own. VBWD_LICENSE_HUB_URL is the online-activation endpoint.
    LICENSE_REQUIRED = os.getenv("VBWD_LICENSE_REQUIRED", "false").lower() == "true"
    LICENSE_KEYS_DIR = os.getenv("VBWD_LICENSE_KEYS_DIR", "var/license/keys")
    LICENSE_PUBLIC_KEY = os.getenv("VBWD_LICENSE_PUBLIC_KEY")
    LICENSE_GRACE_DAYS = int(os.getenv("VBWD_LICENSE_GRACE_DAYS", "14"))
    VBWD_LICENSE_HUB_URL = os.getenv("VBWD_LICENSE_HUB_URL")


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    """Testing configuration."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"  # In-memory for tests

    # Cache off by default in tests; tests that exercise caching install their
    # own InMemoryCacheStore via vbwd.services.cache.set_cache_store.
    CACHE_ENABLED = False

    # Override engine options for SQLite (doesn't support pool_size, max_overflow)
    SQLALCHEMY_ENGINE_OPTIONS = {}

    # Use separate Redis DB for tests
    REDIS_URL = "redis://redis:6379/1"
    CELERY_BROKER_URL = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND = "redis://redis:6379/1"


class ProductionConfig(Config):
    """Production configuration."""

    DEBUG = False
    TESTING = False

    def __init__(self):
        """Initialize production config and validate required env vars."""
        super().__init__()

        # In production, these MUST be set via environment variables
        self.SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
        self.JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

        # Validate FLASK_SECRET_KEY is set
        if not self.SECRET_KEY:
            raise ValueError("FLASK_SECRET_KEY must be set in production")

        # Validate JWT_SECRET_KEY is set
        if not self.JWT_SECRET_KEY:
            raise ValueError("JWT_SECRET_KEY must be set in production")

        # Reject insecure default values
        if self.SECRET_KEY == DEFAULT_SECRET_KEY:
            raise ValueError(
                "FLASK_SECRET_KEY is using insecure default value. "
                "Please set a secure secret key in production."
            )

        if self.JWT_SECRET_KEY == DEFAULT_SECRET_KEY:
            raise ValueError(
                "JWT_SECRET_KEY is using insecure default value. "
                "Please set a secure secret key in production."
            )


# Configuration dictionary
config = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}


def get_config(env: Optional[str] = None) -> Type[Config]:
    """
    Get configuration based on environment.

    Args:
        env: Environment name (development, testing, production)

    Returns:
        Configuration class
    """
    if env is None:
        env = os.getenv("FLASK_ENV", "development")

    return config.get(env, config["default"])

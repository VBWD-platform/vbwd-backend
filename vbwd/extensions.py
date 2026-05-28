"""Flask extensions and database setup."""
import os
from typing import Callable, List, Union

from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from flask_jwt_extended import JWTManager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from vbwd.config import DATABASE_CONFIG, get_redis_url

# SQLAlchemy instance
db = SQLAlchemy()


def _global_default_limits() -> List[Union[str, Callable[[], str]]]:
    """Per-instance ceilings for the global Flask-Limiter, read from env.

    Each value is an integer request count; the window unit is fixed (per
    day / per hour) so ops can tune the number without learning
    Flask-Limiter's mini-DSL. Setting a value to 0 omits that window —
    operators can disable e.g. the day cap entirely.

    Return type matches the Limiter constructor's `default_limits` signature
    (`list[str | Callable[[], str]] | None`) so type-checking flows cleanly
    into the Limiter call site below.

    Raises:
        ValueError: if an env var is set but not a valid integer — fail
        fast so a typo in deployment config crashes app startup instead of
        silently falling through to defaults.
    """
    per_day = int(os.environ.get("RATELIMIT_DEFAULT_DAY", "100000"))
    per_hour = int(os.environ.get("RATELIMIT_DEFAULT_HOUR", "20000"))
    limits: List[Union[str, Callable[[], str]]] = []
    if per_day > 0:
        limits.append(f"{per_day} per day")
    if per_hour > 0:
        limits.append(f"{per_hour} per hour")
    return limits


# Rate limiter - uses Redis for distributed rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=_global_default_limits(),
    storage_uri=get_redis_url(),
    strategy="fixed-window",  # or "moving-window" for stricter limiting
)

# CSRF Protection
# Note: API routes using JWT authentication are exempt (see app.py)
csrf = CSRFProtect()

# JWT Manager for token verification
jwt = JWTManager()


def create_db_engine():
    """
    Create database engine with appropriate settings.

    SQLite doesn't support pool_size, max_overflow, etc.
    PostgreSQL uses full distributed architecture settings.
    """
    db_url = DATABASE_CONFIG["url"]

    # SQLite doesn't support connection pooling options
    if db_url.startswith("sqlite"):
        return create_engine(db_url, echo=False)

    # PostgreSQL with full distributed architecture support
    return create_engine(
        db_url,
        isolation_level=DATABASE_CONFIG["isolation_level"],
        pool_size=DATABASE_CONFIG["pool_size"],
        max_overflow=DATABASE_CONFIG["max_overflow"],
        pool_pre_ping=DATABASE_CONFIG["pool_pre_ping"],
        pool_recycle=DATABASE_CONFIG["pool_recycle"],
        echo=False,
    )


# Create engine
engine = create_db_engine()

# Session factory for direct usage
SessionFactory = sessionmaker(bind=engine)
Session = scoped_session(SessionFactory)

"""S48.1 — connection-pool / worker tuning + graceful degradation.

Guards the invariant that the gunicorn worker count multiplied by the
per-worker connection budget (pool_size + max_overflow) stays safely under
Postgres ``max_connections``. A regression here reintroduces the
``FATAL: sorry, too many clients already`` 500s seen at high concurrency.

Also exercises the env-driven engine-options builder and the graceful
degradation path: pool exhaustion / ``OperationalError`` must surface as a
clean ``503 Service Unavailable`` with a ``Retry-After`` header, never a 500
or a multi-minute hang.
"""
import os
from unittest.mock import patch

from sqlalchemy.exc import OperationalError


# Documented invariant ceiling. Real horizontal scale goes through pgbouncer
# (S48.4), not by raising this number.
POSTGRES_MAX_CONNECTIONS = 200
# Connections reserved for migrations / superuser / admin tooling — never
# handed out to request workers.
CONNECTION_RESERVE = 20


class TestConnectionInvariant:
    """workers x (pool_size + max_overflow) + reserve <= max_connections."""

    def test_default_pool_and_worker_math_fits_postgres(self):
        """The documented default env cannot overcommit Postgres connections."""
        from vbwd.config import build_engine_options, DEFAULT_GUNICORN_WORKERS

        options = build_engine_options(env={})
        per_worker = options["pool_size"] + options["max_overflow"]
        total = DEFAULT_GUNICORN_WORKERS * per_worker

        assert total + CONNECTION_RESERVE <= POSTGRES_MAX_CONNECTIONS, (
            f"workers={DEFAULT_GUNICORN_WORKERS} x per_worker={per_worker} "
            f"= {total}; with reserve {CONNECTION_RESERVE} this exceeds "
            f"Postgres max_connections={POSTGRES_MAX_CONNECTIONS}"
        )

    def test_default_worker_count_is_documented_value(self):
        """The pinned default worker count for the invariant is 4."""
        from vbwd.config import DEFAULT_GUNICORN_WORKERS

        assert DEFAULT_GUNICORN_WORKERS == 4


class TestEngineOptionsBuilder:
    """The engine-options builder reads env and falls back to safe defaults."""

    def test_defaults_are_safe(self):
        """With no env, defaults are the documented safe values."""
        from vbwd.config import build_engine_options

        options = build_engine_options(env={})

        assert options["pool_size"] == 10
        assert options["max_overflow"] == 10
        assert options["pool_timeout"] == 5
        assert options["pool_pre_ping"] is True
        assert options["pool_recycle"] == 3600

    def test_reads_overrides_from_env(self):
        """DB_POOL_SIZE / DB_MAX_OVERFLOW / DB_POOL_TIMEOUT override defaults."""
        from vbwd.config import build_engine_options

        options = build_engine_options(
            env={
                "DB_POOL_SIZE": "25",
                "DB_MAX_OVERFLOW": "15",
                "DB_POOL_TIMEOUT": "8",
            }
        )

        assert options["pool_size"] == 25
        assert options["max_overflow"] == 15
        assert options["pool_timeout"] == 8

    def test_pre_ping_and_recycle_always_present(self):
        """pool_pre_ping and pool_recycle survive env overrides."""
        from vbwd.config import build_engine_options

        options = build_engine_options(env={"DB_POOL_SIZE": "12"})

        assert options["pool_pre_ping"] is True
        assert "pool_recycle" in options

    def test_config_uses_builder_defaults(self):
        """The base Config wires the builder's safe defaults."""
        with patch.dict(os.environ, {}, clear=False):
            for key in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_TIMEOUT"):
                os.environ.pop(key, None)
            import importlib
            import vbwd.config

            importlib.reload(vbwd.config)

            options = vbwd.config.Config.SQLALCHEMY_ENGINE_OPTIONS
            assert options["pool_size"] == 10
            assert options["max_overflow"] == 10
            assert options["pool_timeout"] == 5


def _make_operational_error(message: str) -> OperationalError:
    """Build an OperationalError carrying a driver-style message."""
    return OperationalError(statement="SELECT 1", params={}, orig=Exception(message))


class TestGracefulDegradation:
    """Pool exhaustion surfaces as 503 + Retry-After, never 500/hang."""

    def _build_app(self):
        from vbwd.app import create_app

        app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "SQLALCHEMY_TRACK_MODIFICATIONS": False,
                "RATELIMIT_ENABLED": False,
                "RATELIMIT_STORAGE_URL": "memory://",
            }
        )
        return app

    def test_operational_error_maps_to_503(self):
        """A SQLAlchemy OperationalError becomes a 503 with Retry-After."""
        app = self._build_app()

        @app.route("/_test/pool-exhausted")
        def _pool_exhausted():
            raise _make_operational_error(
                "QueuePool limit of size 10 overflow 10 reached, "
                "connection timed out"
            )

        client = app.test_client()
        response = client.get("/_test/pool-exhausted")

        assert response.status_code == 503
        assert "Retry-After" in response.headers
        assert int(response.headers["Retry-After"]) > 0

    def test_too_many_clients_maps_to_503(self):
        """The Postgres 'too many clients' error also maps to 503."""
        app = self._build_app()

        @app.route("/_test/too-many-clients")
        def _too_many_clients():
            raise _make_operational_error("FATAL:  sorry, too many clients already")

        client = app.test_client()
        response = client.get("/_test/too-many-clients")

        assert response.status_code == 503
        assert "Retry-After" in response.headers

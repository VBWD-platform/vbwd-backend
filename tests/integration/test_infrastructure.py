"""Integration tests for Docker infrastructure and service communication."""
import pytest
import psycopg2
import redis
from sqlalchemy import create_engine, text
from vbwd.config import get_database_url, get_redis_url
from vbwd.app import create_app


class TestDockerInfrastructure:
    """Test Docker services and their interactions."""

    def test_postgres_service_running(self):
        """Test PostgreSQL service is running and accessible."""
        try:
            conn = psycopg2.connect(
                host="postgres",
                port=5432,
                user="vbwd",
                password="vbwd",
                database="vbwd",
            )
            cursor = conn.cursor()
            cursor.execute("SELECT version();")
            version = cursor.fetchone()
            cursor.close()
            conn.close()

            assert version is not None
            assert "PostgreSQL" in version[0]
        except Exception as e:
            pytest.fail(f"PostgreSQL connection failed: {e}")

    def test_redis_service_running(self):
        """Test Redis service is running and accessible."""
        try:
            client = redis.Redis(host="redis", port=6379, decode_responses=True)
            response = client.ping()
            assert response is True
        except Exception as e:
            pytest.fail(f"Redis connection failed: {e}")

    def test_database_url_configuration(self):
        """Test database URL is correctly configured."""
        db_url = get_database_url()
        assert db_url is not None
        assert "postgresql://" in db_url
        assert "postgres:5432" in db_url
        assert "vbwd" in db_url

    def test_redis_url_configuration(self):
        """Test Redis URL is correctly configured."""
        redis_url = get_redis_url()
        assert redis_url is not None
        assert "redis://" in redis_url
        assert "redis:6379" in redis_url

    def test_sqlalchemy_engine_connection(self):
        """Test SQLAlchemy can connect to PostgreSQL."""
        try:
            engine = create_engine(get_database_url())
            with engine.connect() as connection:
                result = connection.execute(text("SELECT 1"))
                assert result.fetchone()[0] == 1
        except Exception as e:
            pytest.fail(f"SQLAlchemy connection failed: {e}")

    def test_database_tables_exist(self):
        """Test that all database tables have been created."""
        expected_tables = [
            "alembic_version",
            "vbwd_currency",
            "vbwd_tax",
            "vbwd_user",
            "vbwd_price",
            "vbwd_tax_rate",
            "vbwd_user_case",
            "vbwd_user_details",
            "vbwd_tarif_plan",
            "vbwd_subscription",
            "vbwd_user_invoice",
        ]

        try:
            engine = create_engine(get_database_url())
            with engine.connect() as connection:
                result = connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
                tables = [row[0] for row in result.fetchall()]

                for table in expected_tables:
                    assert table in tables, f"Table '{table}' not found in database"
        except Exception as e:
            pytest.fail(f"Database table check failed: {e}")

    def test_redis_set_and_get(self):
        """Test Redis can store and retrieve data."""
        try:
            client = redis.Redis(host="redis", port=6379, decode_responses=True)
            test_key = "test:infrastructure"
            test_value = "integration_test"

            # Set value
            client.set(test_key, test_value, ex=60)

            # Get value
            retrieved = client.get(test_key)
            assert retrieved == test_value

            # Cleanup
            client.delete(test_key)
        except Exception as e:
            pytest.fail(f"Redis set/get failed: {e}")

    def test_redis_lock_mechanism(self):
        """Test Redis distributed lock mechanism."""
        from vbwd.utils.redis_client import RedisClient

        try:
            redis_client = RedisClient()
            test_lock_key = "test:lock:infrastructure"

            # Acquire lock
            with redis_client.lock(test_lock_key, timeout=5) as acquired:
                assert acquired is True

                # Try to acquire same lock (should fail/wait)
                with redis_client.lock(
                    test_lock_key, timeout=1, blocking_timeout=0
                ) as acquired2:
                    assert acquired2 is False  # Lock is held
        except Exception as e:
            pytest.fail(f"Redis lock test failed: {e}")

    def test_flask_app_creation(self):
        """Test Flask app can be created successfully."""
        from vbwd.config import get_database_url

        try:
            app = create_app(
                {
                    "TESTING": True,
                    "SQLALCHEMY_DATABASE_URI": get_database_url(),
                    "SQLALCHEMY_TRACK_MODIFICATIONS": False,
                }
            )
            assert app is not None
            assert app.name == "vbwd.app"
        except Exception as e:
            pytest.fail(f"Flask app creation failed: {e}")

    def test_flask_health_endpoint(self, client):
        """Test Flask health endpoint is accessible."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"
        assert data["service"] == "vbwd-api"

    def test_database_connection_pooling(self):
        """Test database connection pooling is configured."""
        from vbwd.extensions import engine

        assert engine is not None
        assert engine.pool.size() == 20  # Configured pool size
        assert engine.pool._max_overflow == 40  # Configured max overflow

    def test_database_isolation_level(self):
        """Test database isolation level is READ COMMITTED."""
        from vbwd.extensions import engine

        with engine.connect() as connection:
            result = connection.execute(text("SHOW transaction_isolation"))
            isolation_level = result.fetchone()[0]
            assert isolation_level == "read committed"

    def test_uuid_support(self):
        """Test PostgreSQL supports UUID data type."""
        try:
            engine = create_engine(get_database_url())
            with engine.connect() as connection:
                # Test UUID column exists in a table
                result = connection.execute(
                    text(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_name = 'vbwd_user' AND column_name = 'id'"
                    )
                )
                row = result.fetchone()
                assert row is not None
                assert row[1] == "uuid", f"Expected UUID type, got {row[1]}"
        except Exception as e:
            pytest.fail(f"UUID support check failed: {e}")

    def test_database_enums_created(self):
        """Test PostgreSQL enum types are created."""
        expected_enums = [
            "userstatus",
            "userrole",
            "subscriptionstatus",
            "invoicestatus",
            "billingperiod",
            "usercasestatus",
        ]

        try:
            engine = create_engine(get_database_url())
            with engine.connect() as connection:
                result = connection.execute(
                    text(
                        "SELECT typname FROM pg_type "
                        "WHERE typtype = 'e' AND typnamespace = "
                        "(SELECT oid FROM pg_namespace WHERE nspname = 'public')"
                    )
                )
                enum_types = [row[0] for row in result.fetchall()]

                for enum in expected_enums:
                    assert enum in enum_types, f"Enum type '{enum}' not found"
        except Exception as e:
            pytest.fail(f"Enum types check failed: {e}")

    def test_cross_service_communication_python_to_postgres(self):
        """Test Python service can communicate with PostgreSQL service."""
        try:
            from vbwd.extensions import engine

            # Test connection via SQLAlchemy
            with engine.connect() as connection:
                result = connection.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
                table_count = result.fetchone()[0]
                assert table_count > 0, "No tables found in database"
        except Exception as e:
            pytest.fail(f"Python-to-PostgreSQL communication failed: {e}")

    def test_cross_service_communication_python_to_redis(self):
        """Test Python service can communicate with Redis service."""
        try:
            from vbwd.utils.redis_client import redis_client

            # Test ping
            assert redis_client.ping() is True

            # Test set/get
            test_key = "test:cross_service"
            redis_client.client.set(test_key, "test_value", ex=60)
            value = redis_client.client.get(test_key)
            assert value == "test_value"

            # Cleanup
            redis_client.client.delete(test_key)
        except Exception as e:
            pytest.fail(f"Python-to-Redis communication failed: {e}")

    def test_all_docker_services_healthy(self):
        """Test all Docker Compose services are healthy."""
        services_status = {
            "postgres": False,
            "redis": False,
            "python": False,
        }

        # Check PostgreSQL
        try:
            conn = psycopg2.connect(
                host="postgres",
                port=5432,
                user="vbwd",
                password="vbwd",
                database="vbwd",
            )
            conn.close()
            services_status["postgres"] = True
        except Exception:
            pass

        # Check Redis
        try:
            client = redis.Redis(host="redis", port=6379)
            client.ping()
            services_status["redis"] = True
        except Exception:
            pass

        # Check Python (Flask app)
        try:
            from vbwd.config import get_database_url

            app = create_app(
                {
                    "TESTING": True,
                    "SQLALCHEMY_DATABASE_URI": get_database_url(),
                    "SQLALCHEMY_TRACK_MODIFICATIONS": False,
                }
            )
            services_status["python"] = app is not None
        except Exception:
            pass

        # Verify all services are healthy
        for service, healthy in services_status.items():
            assert healthy, f"Service '{service}' is not healthy"

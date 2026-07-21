"""Tests for Flask application factory."""


class TestAppFactory:
    """Test cases for create_app factory function."""

    def test_create_app_returns_flask_instance(self, app):
        """create_app should return a Flask application instance."""
        assert app is not None
        assert app.name == "vbwd.app"

    def test_create_app_with_test_config(self):
        """create_app should accept test configuration."""
        from vbwd.app import create_app
        from vbwd.config import get_database_url

        app = create_app(
            {
                "TESTING": True,
                "DEBUG": False,
                "SQLALCHEMY_DATABASE_URI": get_database_url(),
                "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            }
        )

        assert app.config["TESTING"] is True
        assert app.config["DEBUG"] is False

    def test_health_endpoint_returns_ok(self, client):
        """Health endpoint should return 200 OK."""
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        assert response.json["status"] == "ok"
        assert response.json["service"] == "vbwd-api"
        assert "version" in response.json

    def test_root_endpoint_returns_info_or_redirect(self, client):
        """Root endpoint should return API info or redirect to frontend."""
        response = client.get("/")
        # May return 200 (API info) or 302 (redirect to landing/CMS)
        assert response.status_code in (200, 302)

    def test_unknown_api_route_returns_404(self, client):
        """Unknown API routes should return 404."""
        response = client.get("/api/v1/nonexistent")
        assert response.status_code == 404


class TestContainerWiring:
    """Test cases for DI container wiring."""

    def test_app_has_container(self, app):
        """Application should have container attribute."""
        assert hasattr(app, "container")

    def test_container_has_db_session_override(self, app, client):
        """Container should have db_session properly configured."""
        from vbwd.extensions import db

        # Make a request to trigger before_request hook
        client.get("/api/v1/health")

        # Now container should be able to provide services
        with app.app_context():
            app.container.db_session.override(db.session)
            auth_service = app.container.auth_service()
            assert auth_service is not None

    def test_container_provides_working_services(self, app, client):
        """Container services should work with db session."""
        from vbwd.extensions import db
        from vbwd.services.auth_service import AuthService
        from vbwd.services.user_service import UserService

        with app.app_context():
            # Override db_session to simulate request context
            app.container.db_session.override(db.session)

            # Get services from container
            auth_service = app.container.auth_service()
            user_service = app.container.user_service()

            assert isinstance(auth_service, AuthService)
            assert isinstance(user_service, UserService)


class TestEventHandlerRegistration:
    """Test cases for event handler registration during app startup."""

    def test_event_handlers_register_without_dependency_error(self, caplog):
        """Event handlers should register without db_session dependency errors.

        This test verifies that the Container.db_session dependency is properly
        configured before event handlers are registered during app creation.
        """
        import logging
        from vbwd.app import create_app
        from vbwd.config import get_database_url

        caplog.set_level(logging.WARNING)

        # Create app - this should not produce dependency errors
        create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": get_database_url(),
                "SQLALCHEMY_TRACK_MODIFICATIONS": False,
                "RATELIMIT_ENABLED": False,
            }
        )

        # Check that no dependency errors were logged
        dependency_errors = [
            record
            for record in caplog.records
            if "Dependency" in record.message and "not defined" in record.message
        ]

        assert len(dependency_errors) == 0, (
            f"Expected no dependency errors, but found: "
            f"{[r.message for r in dependency_errors]}"
        )

    def test_event_dispatcher_has_handlers_registered(self):
        """Event dispatcher should have password reset handlers registered."""
        from vbwd.app import create_app
        from vbwd.config import get_database_url

        app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": get_database_url(),
                "SQLALCHEMY_TRACK_MODIFICATIONS": False,
                "RATELIMIT_ENABLED": False,
            }
        )

        dispatcher = app.container.event_dispatcher()

        # Check that handlers are registered for security events
        assert "security.password_reset.request" in dispatcher._handlers
        assert "security.password_reset.execute" in dispatcher._handlers


class TestConfig:
    """Test cases for configuration."""

    def test_config_loads_from_environment(self):
        """Configuration should load from environment variables."""
        import os
        from vbwd.config import get_config

        os.environ["FLASK_ENV"] = "testing"
        config = get_config("testing")

        assert config.TESTING is True
        assert config.SQLALCHEMY_DATABASE_URI == "sqlite:///:memory:"

    def test_database_url_helper(self):
        """get_database_url should return correct URL."""
        from vbwd.config import get_database_url

        url = get_database_url()
        assert url is not None
        assert "postgresql://" in url or "sqlite://" in url

    def test_redis_url_helper(self):
        """get_redis_url should return correct URL."""
        from vbwd.config import get_redis_url

        url = get_redis_url()
        assert url is not None
        assert "redis://" in url


class TestForwardedProtoHandling:
    """TLS terminates on an outer proxy, so Flask must trust X-Forwarded-Proto.

    Without it every Werkzeug-generated redirect (``merge_slashes`` 308s,
    ``url_for(..., _external=True)``) emits an ``http://`` absolute URL that the
    browser blocks as mixed content on an https:// page.
    """

    REDIRECTING_PATH = "/api/v1//health"  # doubled slash -> merge_slashes 308

    @staticmethod
    def _create_app(extra_config=None):
        from vbwd.app import create_app
        from vbwd.config import get_database_url

        app_config = {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": get_database_url(),
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "RATELIMIT_ENABLED": False,
        }
        app_config.update(extra_config or {})
        app = create_app(app_config)

        from flask import request, url_for

        @app.route("/_test/echo-scheme")
        def echo_scheme():
            return {
                "scheme": request.scheme,
                "external_url": url_for("echo_scheme", _external=True),
            }

        return app

    def test_redirect_location_uses_forwarded_https_scheme(self):
        """X-Forwarded-Proto: https must produce an https:// Location."""
        client = self._create_app().test_client()

        response = client.get(
            self.REDIRECTING_PATH,
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "vbwd.cc"},
        )

        assert response.status_code in (301, 302, 307, 308)
        assert response.headers["Location"].startswith("https://")

    def test_redirect_location_stays_http_without_forwarded_header(self):
        """Un-proxied requests keep the plain http:// behaviour."""
        client = self._create_app().test_client()

        response = client.get(self.REDIRECTING_PATH)

        assert response.status_code in (301, 302, 307, 308)
        assert response.headers["Location"].startswith("http://")

    def test_request_scheme_and_external_url_follow_forwarded_proto(self):
        """request.scheme and url_for(_external=True) must reflect the proxy."""
        client = self._create_app().test_client()

        response = client.get(
            "/_test/echo-scheme",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "vbwd.cc"},
        )

        assert response.json["scheme"] == "https"
        assert response.json["external_url"].startswith("https://vbwd.cc/")

    def test_proxy_fix_can_be_disabled(self):
        """PROXY_FIX_ENABLED=False must ignore the forwarded headers entirely."""
        client = self._create_app({"PROXY_FIX_ENABLED": False}).test_client()

        response = client.get(
            "/_test/echo-scheme",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "vbwd.cc"},
        )

        assert response.json["scheme"] == "http"

    def test_trusted_hop_counts_are_configurable(self):
        """Hop counts come from config so the deployment topology can differ."""
        from werkzeug.middleware.proxy_fix import ProxyFix

        app = self._create_app(
            {"PROXY_FIX_X_FOR": 3, "PROXY_FIX_X_PROTO": 2, "PROXY_FIX_X_HOST": 0}
        )

        assert isinstance(app.wsgi_app, ProxyFix)
        assert app.wsgi_app.x_for == 3
        assert app.wsgi_app.x_proto == 2
        assert app.wsgi_app.x_host == 0

    def test_default_hop_counts_match_production_topology(self):
        """Defaults: two X-Forwarded-For hops, one proto/host hop."""
        from werkzeug.middleware.proxy_fix import ProxyFix

        app = self._create_app()

        assert isinstance(app.wsgi_app, ProxyFix)
        assert app.wsgi_app.x_for == 2
        assert app.wsgi_app.x_proto == 1
        assert app.wsgi_app.x_host == 1

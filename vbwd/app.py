"""Flask application factory."""
import os
from flask import Flask, jsonify, make_response, request
from flask_limiter.util import get_remote_address
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


def _install_unified_logging(app: Flask, container) -> None:
    """Install the D9 unified logging layer (Sprint 58.5).

    Attaches a single :class:`VbwdLogRouter` to the root logger and registers
    one :class:`EventLogSubscriber` on the EventBus, both writing through the
    FilesystemManager's ``logs`` namespace.

    GUARDED like the schedulers: the disk router is NOT attached during the
    test suite (``TESTING``) so pytest is not polluted and does not try to write
    ``/app/var/logs``; the console handler stays. The whole wiring is
    best-effort — if the ``logs`` root is not writable the app still boots and
    logging degrades to stderr.
    """
    if app.config.get("TESTING"):
        return
    try:
        from vbwd.events.bus import event_bus
        from vbwd.services.logging import (
            EventLogSubscriber,
            LoggingConfig,
            VbwdLogRouter,
        )

        filesystem_manager = container.filesystem_manager()

        max_bytes = int(
            app.config.get(
                "LOG_MAX_BYTES", os.getenv("VBWD_LOG_MAX_BYTES", "") or 10 * 1024 * 1024
            )
        )
        backups = int(
            app.config.get("LOG_BACKUPS", os.getenv("VBWD_LOG_BACKUPS", "") or 5)
        )
        logging_config = LoggingConfig(max_bytes=max_bytes, backups=backups)

        router = VbwdLogRouter(
            filesystem_manager=filesystem_manager, config=logging_config
        )
        root_logger = logging.getLogger()
        # Idempotent: never attach a second router on app re-creation.
        if not any(
            isinstance(handler, VbwdLogRouter) for handler in root_logger.handlers
        ):
            root_logger.addHandler(router)
        if root_logger.level > logging.INFO or root_logger.level == logging.NOTSET:
            root_logger.setLevel(logging.INFO)

        EventLogSubscriber(filesystem_manager=filesystem_manager).register(event_bus)
        logger.info("Unified logging (D9) installed")
    except Exception as logging_error:  # noqa: BLE001 — boot must survive
        logger.warning("Failed to install unified logging: %s", logging_error)


def _register_event_handlers(app: Flask, container) -> None:
    """
    Register event handlers with the dispatcher.

    Args:
        app: Flask application instance
        container: DI container
    """
    from vbwd.handlers.password_reset_handler import (
        PasswordResetExecuteHandler,
        PasswordResetRequestHandler,
    )
    from vbwd.handlers.payment_handler import PaymentCapturedHandler
    from vbwd.handlers.refund_handler import PaymentRefundedHandler
    from vbwd.handlers.restore_handler import RefundReversedHandler
    from vbwd.handlers.payment_authorized_handler import PaymentAuthorizedHandler

    try:
        dispatcher = container.event_dispatcher()

        # Create a mock email service for now if not configured
        # In production, this should be properly configured
        class MockEmailService:
            def send_template(
                self, to: str, template: str, context: dict, subject=None
            ) -> object:
                logger.info(f"[MockEmail] Would send '{template}' to {to}")
                return type("EmailResult", (), {"success": True})()

            def register_template_path(self, template_dir: str) -> None:
                pass

        email_service: Any = MockEmailService()

        # S13 — split into two single-purpose handlers (SRP/OCP).
        reset_url_base = app.config.get(
            "RESET_URL_BASE", "http://localhost:5173/reset-password"
        )
        request_handler = PasswordResetRequestHandler(
            password_reset_service=container.password_reset_service(),
            email_service=email_service,
            activity_logger=container.activity_logger(),
            reset_url_base=reset_url_base,
        )
        execute_handler = PasswordResetExecuteHandler(
            password_reset_service=container.password_reset_service(),
            email_service=email_service,
            activity_logger=container.activity_logger(),
        )
        dispatcher.register("security.password_reset.request", request_handler)
        dispatcher.register("security.password_reset.execute", execute_handler)

        # Register core line item handler (TOKEN_BUNDLE only)
        # Must be registered BEFORE plugins so core handlers have priority
        from vbwd.events.line_item_registry import line_item_registry
        from vbwd.handlers.core_line_item_handler import CoreLineItemHandler

        core_line_item_handler = CoreLineItemHandler(container)
        line_item_registry.register(core_line_item_handler)

        # Create payment handler with container for request-scoped repos
        payment_handler = PaymentCapturedHandler(container)

        # Register payment handler
        dispatcher.register("payment.captured", payment_handler)

        # Create and register refund handler
        refund_handler = PaymentRefundedHandler(container)
        dispatcher.register("payment.refunded", refund_handler)

        # Create and register refund reversal handler
        restore_handler = RefundReversedHandler(container)
        dispatcher.register("refund.reversed", restore_handler)

        # Create and register payment authorized handler
        authorized_handler = PaymentAuthorizedHandler(container)
        dispatcher.register("payment.authorized", authorized_handler)

        logger.info("Event handlers registered successfully")

    except Exception as e:
        logger.warning(f"Failed to register event handlers: {e}")


def create_app(config: Optional[Dict[str, Any]] = None) -> Flask:
    """
    Create and configure Flask application.

    Args:
        config: Optional configuration dictionary to override defaults.

    Returns:
        Configured Flask application instance.
    """
    app = Flask(__name__)

    # Disable strict slashes to prevent redirects that break nginx proxy
    app.url_map.strict_slashes = False

    # Load configuration
    if config:
        app.config.update(config)
    else:
        from vbwd.config import get_config

        app.config.from_object(get_config())

    # Initialize extensions
    from vbwd.extensions import db, limiter, csrf, jwt

    db.init_app(app)
    limiter.init_app(app)
    csrf.init_app(app)
    jwt.init_app(app)

    # Exempt API routes from CSRF (they use JWT authentication)
    # CSRF is only needed for browser form submissions, not API calls
    from vbwd.routes.auth import auth_bp
    from vbwd.routes.user import user_bp
    from vbwd.routes.invoices import invoices_bp
    from vbwd.routes.events import events_bp
    from vbwd.routes.admin import (
        admin_users_bp,
        admin_invoices_bp,
        admin_profile_bp,
        admin_token_bundles_bp,
        admin_settings_bp,
        admin_payment_methods_bp,
        admin_countries_bp,
        admin_plugins_bp,
        admin_tax_bp,
    )
    from vbwd.routes.admin.access import access_bp as admin_access_bp
    from vbwd.routes.admin.data_exchange import data_exchange_bp
    from vbwd.routes.admin.frontend_plugins import frontend_plugins_bp
    from vbwd.routes.config import config_bp
    from vbwd.routes.settings import settings_bp
    from vbwd.routes.token_bundles import token_bundles_bp
    from vbwd.routes.webhooks import webhooks_bp

    csrf.exempt(auth_bp)
    csrf.exempt(user_bp)
    csrf.exempt(invoices_bp)
    csrf.exempt(events_bp)
    csrf.exempt(admin_users_bp)
    csrf.exempt(admin_invoices_bp)
    csrf.exempt(admin_profile_bp)
    csrf.exempt(admin_token_bundles_bp)
    csrf.exempt(admin_settings_bp)
    csrf.exempt(admin_payment_methods_bp)
    csrf.exempt(admin_countries_bp)
    csrf.exempt(admin_plugins_bp)
    csrf.exempt(admin_tax_bp)
    csrf.exempt(admin_access_bp)
    csrf.exempt(data_exchange_bp)
    csrf.exempt(frontend_plugins_bp)
    csrf.exempt(token_bundles_bp)
    csrf.exempt(config_bp)
    csrf.exempt(settings_bp)
    csrf.exempt(webhooks_bp)

    # Initialize DI container
    from vbwd.container import Container

    container = Container()

    # Wire container to use Flask-SQLAlchemy session
    # Initial override for app startup (event handlers, etc.)
    # Per-request override happens in before_request hook
    app.container = container  # type: ignore[attr-defined]

    # Override db_session for app initialization (required for event handlers)
    with app.app_context():
        container.db_session.override(db.session)

    @app.before_request
    def inject_db_session():
        """Inject db session into container for each request."""
        container.db_session.override(db.session)

    # Register event handlers (now db_session is available)
    with app.app_context():
        _register_event_handlers(app, container)

    # Install the unified logging layer (D9) — root log router + event audit
    # subscriber. TESTING-guarded so the disk router is not attached under
    # pytest (see _install_unified_logging).
    with app.app_context():
        _install_unified_logging(app, container)

    # Initialize plugin system
    from vbwd.plugins.manager import PluginManager
    from vbwd.plugins.json_config_store import JsonFilePluginConfigStore
    from vbwd.plugins.config_schema import PluginConfigSchemaReader

    plugins_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")
    config_store = JsonFilePluginConfigStore(plugins_dir)
    schema_reader = PluginConfigSchemaReader([plugins_dir])
    plugin_manager = PluginManager(config_repo=config_store)
    app.plugin_manager = plugin_manager  # type: ignore[attr-defined]
    app.config_store = config_store  # type: ignore[attr-defined]
    app.schema_reader = schema_reader  # type: ignore[attr-defined]

    # Auto-discover plugins from user plugins dir
    plugin_manager.discover("plugins")

    # Load persisted state from DB; if nothing is enabled (fresh install),
    # bootstrap from plugins/plugins.json.dist so any plugin can be a
    # default just by editing that file — no hardcoded names in core (S06).
    with app.app_context():
        plugin_manager.load_persisted_state()
        if not plugin_manager.get_enabled_plugins():
            import json

            dist_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "plugins",
                "plugins.json.dist",
            )
            if os.path.exists(dist_path):
                with open(dist_path) as dist_handle:
                    dist_config = json.load(dist_handle)
                for default_name, default_cfg in dist_config.get("plugins", {}).items():
                    if not default_cfg.get("enabled"):
                        continue
                    try:
                        plugin_manager.enable_plugin(default_name)
                    except ValueError:
                        # plugin listed in dist but not installed — skip silently
                        pass

    # Register regular + admin blueprints for every plugin — agnostic loop;
    # plugins with no admin BP inherit BasePlugin.get_admin_blueprint() = None.
    for plugin in plugin_manager.get_all_plugins():
        bp = plugin.get_blueprint()
        if bp:
            csrf.exempt(bp)
            app.register_blueprint(bp, url_prefix=plugin.get_url_prefix())
        admin_bp = plugin.get_admin_blueprint()
        if admin_bp:
            csrf.exempt(admin_bp)
            app.register_blueprint(admin_bp)

    # Register blueprints (already imported above for CSRF exemption)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(admin_users_bp)
    app.register_blueprint(admin_invoices_bp)
    app.register_blueprint(admin_profile_bp)
    app.register_blueprint(admin_token_bundles_bp)
    app.register_blueprint(admin_settings_bp)
    app.register_blueprint(admin_payment_methods_bp)
    app.register_blueprint(admin_countries_bp)
    app.register_blueprint(admin_plugins_bp)
    app.register_blueprint(admin_tax_bp)
    app.register_blueprint(admin_access_bp)
    app.register_blueprint(data_exchange_bp)
    app.register_blueprint(frontend_plugins_bp)
    app.register_blueprint(token_bundles_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(webhooks_bp)

    # Register the core data-exchange entity exchangers (S46.1). These are CORE
    # entities (users+details, invoices, payment methods, access levels, email
    # templates, currencies, countries), so — unlike plugin exchangers, which
    # register at plugin enable-time — they register directly at init, before
    # the permission catalog is collected, so their sales-cluster export/import
    # permissions surface in the Access Level form. Idempotent / clear-safe.
    from vbwd.services.data_exchange.core_exchangers import register_core_exchangers

    with app.app_context():
        register_core_exchangers(db.session)

    # S30 — debug-only load-test introspection (/_routes, /_seed_status).
    # The whole blueprint is gated per-route by require_debug_enabled; the
    # ENABLE_DEBUG_ENDPOINTS flag (below) defaults OFF so prod is unaffected.
    from vbwd.routes.debug import debug_bp

    csrf.exempt(debug_bp)
    app.register_blueprint(debug_bp)
    if "ENABLE_DEBUG_ENDPOINTS" not in app.config:
        app.config["ENABLE_DEBUG_ENDPOINTS"] = os.getenv(
            "VBWD_ENABLE_DEBUG_ENDPOINTS", ""
        ).lower() in ("1", "true", "yes")

    # Health check endpoint — cheap liveness (process alive); no I/O.
    @app.route("/api/v1/health")
    def health():
        """Health check endpoint."""
        return jsonify({"status": "ok", "service": "vbwd-api", "version": "0.1.0"}), 200

    # S14 — readiness probe (DB connectivity); used by load balancers /
    # k8s readiness probes so traffic is routed away when the DB is down,
    # without the container restart loop a liveness failure would trigger.
    @app.route("/api/v1/ready")
    def ready():
        """Readiness probe — verifies DB is reachable."""
        from vbwd.extensions import db
        from sqlalchemy import text

        try:
            db.session.execute(text("SELECT 1"))
            return jsonify({"db": True}), 200
        except Exception as probe_error:  # noqa: BLE001 — broad by design
            return (
                jsonify({"db": False, "error": str(probe_error)}),
                503,
            )

    # Root endpoint
    @app.route("/")
    def root():
        """Root endpoint."""
        return (
            jsonify(
                {"message": "VBWD API", "version": "0.1.0", "health": "/api/v1/health"}
            ),
            200,
        )

    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 errors."""
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 errors."""
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(429)
    def ratelimit_handler(error):
        """Handle rate limit exceeded errors with JSON response."""
        # S33 — structured telemetry: one WARN line per 429 so "users hit the
        # cap" reports are answerable with grep (route + bucket key + the
        # tripped descriptor). The bucket key uses the limiter's current
        # keyfunc (get_remote_address); S31 will swap that for a per-user key.
        logger.warning(
            "429 route=%s key=%s descriptor=%s",
            request.endpoint or request.path,
            get_remote_address(),
            str(error.description),
        )
        response = make_response(
            jsonify(
                {"error": "Rate limit exceeded", "message": str(error.description)}
            ),
            429,
        )
        # Add Retry-After header from the error if available
        if (
            hasattr(error, "description")
            and "retry after" in str(error.description).lower()
        ):
            # Extract retry time from description
            import re

            match = re.search(
                r"(\d+)\s*(second|minute)", str(error.description).lower()
            )
            if match:
                value = int(match.group(1))
                unit = match.group(2)
                retry_after = value if "second" in unit else value * 60
                response.headers["Retry-After"] = str(retry_after)
        else:
            # Default to 60 seconds
            response.headers["Retry-After"] = "60"
        return response

    # Register CLI commands
    from vbwd.cli.test_data import seed_test_data_command, cleanup_test_data_command
    from vbwd.cli.reset_demo import reset_demo_command
    from vbwd.cli.plugins import plugins_cli
    from vbwd.cli.seed_rbac import seed_rbac_command
    from vbwd.cli.seed_countries import seed_countries_command
    from vbwd.cli.seed_payment_methods import seed_payment_methods_command
    from vbwd.cli.seed import seed_command
    from vbwd.cli.data_exchange import data_exchange_group

    app.cli.add_command(seed_test_data_command)
    app.cli.add_command(cleanup_test_data_command)
    app.cli.add_command(reset_demo_command)
    app.cli.add_command(plugins_cli)
    app.cli.add_command(seed_rbac_command)
    app.cli.add_command(seed_countries_command)
    app.cli.add_command(seed_payment_methods_command)
    app.cli.add_command(seed_command)
    app.cli.add_command(data_exchange_group)

    return app

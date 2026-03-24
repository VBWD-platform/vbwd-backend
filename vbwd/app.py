"""Flask application factory."""
import os
from flask import Flask, jsonify, make_response
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


def _register_event_handlers(app: Flask, container) -> None:
    """
    Register event handlers with the dispatcher.

    Args:
        app: Flask application instance
        container: DI container
    """
    from vbwd.handlers.password_reset_handler import PasswordResetHandler
    from vbwd.handlers.checkout_handler import CheckoutHandler
    from vbwd.handlers.payment_handler import PaymentCapturedHandler
    from vbwd.handlers.refund_handler import PaymentRefundedHandler
    from vbwd.handlers.restore_handler import RefundReversedHandler
    from vbwd.handlers.subscription_cancel_handler import SubscriptionCancelledHandler
    from vbwd.handlers.payment_failed_handler import PaymentFailedHandler
    from vbwd.handlers.payment_authorized_handler import PaymentAuthorizedHandler

    try:
        dispatcher = container.event_dispatcher()

        # Create a mock email service for now if not configured
        # In production, this should be properly configured
        class MockEmailService:
            def send_template(self, to: str, template: str, context: dict) -> object:
                logger.info(f"[MockEmail] Would send '{template}' to {to}")
                return type("EmailResult", (), {"success": True})()

        email_service: Any = MockEmailService()

        # Create password reset handler
        password_reset_handler = PasswordResetHandler(
            password_reset_service=container.password_reset_service(),
            email_service=email_service,
            activity_logger=container.activity_logger(),
            reset_url_base=app.config.get(
                "RESET_URL_BASE", "http://localhost:5173/reset-password"
            ),
        )

        # Register handlers for security events
        dispatcher.register("security.password_reset.request", password_reset_handler)
        dispatcher.register("security.password_reset.execute", password_reset_handler)

        # Create checkout handler with container for request-scoped repos
        checkout_handler = CheckoutHandler(container)

        # Register checkout handler
        dispatcher.register("checkout.requested", checkout_handler)

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

        # Create and register subscription cancel handler
        cancel_handler = SubscriptionCancelledHandler(container)
        dispatcher.register("subscription.cancelled", cancel_handler)

        # Create and register payment failed handler
        payment_failed_handler = PaymentFailedHandler(container)
        dispatcher.register("payment.failed", payment_failed_handler)

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
    from vbwd.routes.tarif_plans import tarif_plans_bp
    from vbwd.routes.subscriptions import subscriptions_bp
    from vbwd.routes.invoices import invoices_bp
    from vbwd.routes.events import events_bp
    from vbwd.routes.admin import (
        admin_users_bp,
        admin_subs_bp,
        admin_invoices_bp,
        admin_plans_bp,
        admin_profile_bp,
        admin_token_bundles_bp,
        admin_addons_bp,
        admin_settings_bp,
        admin_payment_methods_bp,
        admin_countries_bp,
        admin_plugins_bp,
        admin_categories_bp,
    )
    from vbwd.routes.config import config_bp
    from vbwd.routes.addons import addons_bp
    from vbwd.routes.settings import settings_bp
    from vbwd.routes.token_bundles import token_bundles_bp
    from vbwd.routes.webhooks import webhooks_bp

    csrf.exempt(auth_bp)
    csrf.exempt(user_bp)
    csrf.exempt(tarif_plans_bp)
    csrf.exempt(subscriptions_bp)
    csrf.exempt(invoices_bp)
    csrf.exempt(events_bp)
    csrf.exempt(admin_users_bp)
    csrf.exempt(admin_subs_bp)
    csrf.exempt(admin_invoices_bp)
    csrf.exempt(admin_plans_bp)
    csrf.exempt(admin_profile_bp)
    csrf.exempt(admin_token_bundles_bp)
    csrf.exempt(admin_addons_bp)
    csrf.exempt(admin_settings_bp)
    csrf.exempt(admin_payment_methods_bp)
    csrf.exempt(admin_countries_bp)
    csrf.exempt(admin_plugins_bp)
    csrf.exempt(admin_categories_bp)
    csrf.exempt(addons_bp)
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

    # Load persisted state from DB; default-enable analytics on first run
    with app.app_context():
        plugin_manager.load_persisted_state()
        if not plugin_manager.get_enabled_plugins():
            try:
                plugin_manager.enable_plugin("analytics")
            except ValueError:
                # Analytics plugin may not exist, skip if unavailable
                pass

    # Register ALL plugin blueprints at startup (route handlers check enabled status)
    analytics_plugin = None
    for plugin in plugin_manager.get_all_plugins():
        if plugin.metadata.name == "analytics":
            analytics_plugin = plugin
        bp = plugin.get_blueprint()
        if bp:
            csrf.exempt(bp)
            app.register_blueprint(bp, url_prefix=plugin.get_url_prefix())

    # Register analytics admin blueprint from plugin (for /admin/analytics routes)
    if analytics_plugin:
        admin_bp = analytics_plugin.get_admin_blueprint()
        if admin_bp:
            csrf.exempt(admin_bp)
            app.register_blueprint(admin_bp)

    # Register blueprints (already imported above for CSRF exemption)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(tarif_plans_bp, url_prefix="/api/v1/tarif-plans")
    app.register_blueprint(subscriptions_bp, url_prefix="/api/v1/user/subscriptions")
    app.register_blueprint(invoices_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(admin_users_bp)
    app.register_blueprint(admin_subs_bp)
    app.register_blueprint(admin_invoices_bp)
    app.register_blueprint(admin_plans_bp)
    app.register_blueprint(admin_profile_bp)
    app.register_blueprint(admin_token_bundles_bp)
    app.register_blueprint(admin_addons_bp)
    app.register_blueprint(admin_settings_bp)
    app.register_blueprint(admin_payment_methods_bp)
    app.register_blueprint(admin_countries_bp)
    app.register_blueprint(admin_plugins_bp)
    app.register_blueprint(admin_categories_bp)
    app.register_blueprint(addons_bp)
    app.register_blueprint(token_bundles_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(webhooks_bp)

    # Health check endpoint
    @app.route("/api/v1/health")
    def health():
        """Health check endpoint."""
        return jsonify({"status": "ok", "service": "vbwd-api", "version": "0.1.0"}), 200

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

    app.cli.add_command(seed_test_data_command)
    app.cli.add_command(cleanup_test_data_command)
    app.cli.add_command(reset_demo_command)
    app.cli.add_command(plugins_cli)

    if not app.config.get("TESTING"):
        from vbwd.scheduler import start_subscription_scheduler

        start_subscription_scheduler(app)

    return app

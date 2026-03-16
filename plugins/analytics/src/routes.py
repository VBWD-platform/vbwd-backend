"""Analytics plugin API routes."""
from flask import Blueprint, jsonify, current_app
from sqlalchemy import func
from src.middleware.auth import require_auth, require_admin
from src.extensions import db
from src.models.user import User
from src.models.subscription import Subscription
from src.models.invoice import UserInvoice
from src.models.enums import SubscriptionStatus, InvoiceStatus

# Blueprint for admin analytics (handles core dashboard analytics)
analytics_admin_bp = Blueprint(
    "analytics_admin", __name__, url_prefix="/api/v1/admin/analytics"
)

# Blueprint for plugin-specific analytics endpoints
analytics_plugin_bp = Blueprint("analytics_plugin", __name__)


@analytics_admin_bp.route("/dashboard", methods=["GET"])
@require_auth
@require_admin
def get_dashboard():
    """
    Get dashboard analytics.

    Returns aggregated metrics for the admin dashboard:
    - mrr: Monthly Recurring Revenue
    - revenue: Total revenue from paid invoices
    - user_growth: Total user count
    - active_subscriptions: Count of active subscriptions

    Returns:
        200: Dashboard metrics
    """
    # Count total users
    total_users = db.session.query(func.count(User.id)).scalar() or 0

    # Count active subscriptions
    active_subscriptions = (
        db.session.query(func.count(Subscription.id))
        .filter(Subscription.status == SubscriptionStatus.ACTIVE)
        .scalar()
        or 0
    )

    # Calculate total revenue from paid invoices
    total_revenue = (
        db.session.query(func.sum(UserInvoice.amount))
        .filter(UserInvoice.status == InvoiceStatus.PAID)
        .scalar()
        or 0
    )

    # MRR is approximated from active subscriptions
    # In a real system, this would calculate based on subscription prices
    mrr = float(total_revenue) / 12 if total_revenue else 0

    return (
        jsonify(
            {
                "mrr": {"total": round(mrr, 2), "change_percent": 0},
                "revenue": {"total": float(total_revenue), "change_percent": 0},
                "user_growth": {"total": total_users, "change_percent": 0},
                "active_subscriptions": {
                    "total": active_subscriptions,
                    "change_percent": 0,
                },
                "churn": {"total": 0, "change_percent": 0},
                "conversion": {"total": 0, "change_percent": 0},
                "arpu": {
                    "total": round(float(total_revenue) / total_users, 2)
                    if total_users > 0
                    else 0,
                    "change_percent": 0,
                },
            }
        ),
        200,
    )


@analytics_plugin_bp.route("/active-sessions", methods=["GET"])
@require_auth
@require_admin
def get_active_sessions():
    """Get active sessions count from analytics plugin."""
    config_store = getattr(current_app, "config_store", None)
    if not config_store:
        return jsonify({"error": "Plugin system not available"}), 404

    entry = config_store.get_by_name("analytics")
    if not entry or entry.status != "enabled":
        return jsonify({"error": "Analytics plugin not enabled"}), 404

    plugin_manager = getattr(current_app, "plugin_manager", None)
    if not plugin_manager:
        return jsonify({"error": "Plugin system not available"}), 404

    plugin = plugin_manager.get_plugin("analytics")
    if not plugin:
        return jsonify({"error": "Analytics plugin not found"}), 404

    return jsonify(plugin.get_active_sessions()), 200

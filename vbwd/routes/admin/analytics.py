"""Admin analytics routes."""
from flask import Blueprint, jsonify
from sqlalchemy import func
from vbwd.middleware.auth import require_auth, require_admin, require_permission
from vbwd.extensions import db
from vbwd.models.user import User
from vbwd.models.subscription import Subscription
from vbwd.models.invoice import UserInvoice
from vbwd.models.enums import SubscriptionStatus, InvoiceStatus

admin_analytics_bp = Blueprint(
    "admin_analytics", __name__, url_prefix="/api/v1/admin/analytics"
)


@admin_analytics_bp.route("/dashboard", methods=["GET"])
@require_auth
@require_admin
@require_permission("analytics.view")
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

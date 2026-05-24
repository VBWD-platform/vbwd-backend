"""Demo data seeder — resets transactional data and seeds clean catalog."""
from sqlalchemy.orm import Session
from sqlalchemy import text


# Demo catalog definition. Plan/addon demo data is owned by the
# subscription plugin (plugins/subscription/subscription/demo_seed.py);
# core only seeds token bundles.
DEMO_TOKEN_BUNDLES = [
    {
        "name": "Starter Pack (500)",
        "description": "500 tokens for light usage.",
        "token_amount": 500,
        "price": 5.00,
        "is_active": True,
        "sort_order": 1,
    },
    {
        "name": "Standard Pack (1000)",
        "description": "1,000 tokens — best for regular use.",
        "token_amount": 1000,
        "price": 10.00,
        "is_active": True,
        "sort_order": 2,
    },
    {
        "name": "Pro Pack (5000)",
        "description": "5,000 tokens at a 10% discount.",
        "token_amount": 5000,
        "price": 45.00,
        "is_active": True,
        "sort_order": 3,
    },
]


class DemoSeeder:
    """Reset transactional data and seed clean demo catalog."""

    def __init__(self, db_session: Session):
        self.session = db_session

    def run(self) -> dict:
        """Execute full reset and return stats."""
        stats = {}
        stats.update(self._clear_transactional_data())
        stats.update(self._clear_catalog())
        stats.update(self._seed_catalog())
        self.session.commit()
        return stats

    def _clear_transactional_data(self) -> dict:
        """Delete all invoices, subscriptions, purchases, balances."""
        counts = {}
        # Order matters: children before parents (FK constraints)
        tables = [
            "token_transaction",
            "token_bundle_purchase",
            "addon_subscription",
            "invoice_line_item",
            "user_invoice",
            "subscription",
            "user_token_balance",
            "feature_usage",
            "password_reset_token",
        ]
        for table in tables:
            result = self.session.execute(text(f"DELETE FROM {table}"))
            counts[f"deleted_{table}"] = result.rowcount  # type: ignore[attr-defined]
        return counts

    def _clear_catalog(self) -> dict:
        """Delete all plans, addons, token bundles, and orphan prices."""
        counts = {}

        # Null out price_id FK on tarif_plan before deleting prices
        self.session.execute(text("UPDATE tarif_plan SET price_id = NULL"))

        for table in ["tarif_plan", "addon", "token_bundle", "price"]:
            result = self.session.execute(text(f"DELETE FROM {table}"))
            counts[f"deleted_{table}"] = result.rowcount  # type: ignore[attr-defined]

        return counts

    def _seed_catalog(self) -> dict:
        """Insert demo token bundles (core); delegate plan/addon catalog to
        feature plugins via the demo-data registry."""
        from vbwd.models.token_bundle import TokenBundle
        from vbwd.services.demo_data_registry import run_catalog_seeders

        for b in DEMO_TOKEN_BUNDLES:
            bundle = TokenBundle(
                name=b["name"],
                description=b["description"],
                token_amount=b["token_amount"],
                price=b["price"],
                is_active=b["is_active"],
                sort_order=b["sort_order"],
            )
            self.session.add(bundle)

        self.session.flush()

        # Subscription (plans/addons) catalog is owned by the subscription
        # plugin; no-op when the plugin is disabled.
        run_catalog_seeders(self.session)
        self.session.flush()

        return {
            "seeded_token_bundles": len(DEMO_TOKEN_BUNDLES),
        }

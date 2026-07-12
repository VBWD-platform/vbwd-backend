"""Demo data seeder — resets transactional data and seeds clean catalog."""
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


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
        """Execute full reset and return stats.

        Order matters: plugin clearers → clear core → seed core/plugin catalogs
        (incl. CMS pages/widgets/layouts) → seed countries → run post-seed hooks
        (the CMS backfill that folds the just-seeded pages into the unified
        cms_post model). Catalog + post-seed work is contributed by plugins
        through the demo-data registry, so core never imports a plugin model.
        """
        stats = {}
        # Plugin-registered clearers run FIRST, before core clears its own
        # tables. A plugin whose table references a core table (e.g. a booking
        # reservation → vbwd_user_invoice, a dataset↔tax link → vbwd_tax) purges
        # its rows here so the subsequent core DELETEs are FK-safe. Core names no
        # plugin table — the ownership stays in the plugin.
        stats.update(self._run_catalog_clearers())
        stats.update(self._clear_transactional_data())
        stats.update(self._clear_catalog())
        stats.update(self._seed_catalog())
        stats.update(self._seed_countries())
        stats.update(self._run_post_seed_hooks())
        self.session.commit()
        return stats

    def _table_exists(self, table_name: str) -> bool:
        """True when ``table_name`` is present in the bound database.

        Guards the clear step so a not-installed plugin's table never aborts
        the reset (the historical ``relation "token_transaction" does not
        exist`` crash). A separate seam so unit tests can stub it.
        """
        bind = self.session.get_bind()
        return inspect(bind).has_table(table_name)

    def _seed_countries(self) -> dict:
        """Ensure the foundational country catalog exists.

        Delegates to the core country seeder (single source of truth, DRY).
        Idempotent: existing rows and operator enable/disable edits survive.
        """
        from vbwd.services.country_seeder import seed_countries

        result = seed_countries(self.session)
        return {"countries_created": result.created}

    def _clear_transactional_data(self) -> dict:
        """Delete all invoices, subscriptions, purchases, balances."""
        counts = {}
        # Order matters: children before parents (FK constraints)
        # Current (post-extraction) table names. Children before parents (FK
        # order). Each is guarded by ``_table_exists`` so a not-installed
        # plugin's table is skipped rather than aborting the reset (the
        # historical ``relation … does not exist`` crash).
        tables = [
            "vbwd_token_transaction",
            "vbwd_token_bundle_purchase",
            "subscription_addon_subscription",
            "vbwd_invoice_line_item",
            "vbwd_user_invoice",
            "subscription_record",
            "vbwd_user_token_balance",
            "vbwd_feature_usage",
            "vbwd_password_reset_token",
        ]
        for table in tables:
            if not self._table_exists(table):
                continue
            result = self.session.execute(text(f"DELETE FROM {table}"))
            counts[f"deleted_{table}"] = result.rowcount  # type: ignore[attr-defined]
        return counts

    def _clear_catalog(self) -> dict:
        """Delete all plans, addons, and token bundles (skip absent tables)."""
        counts = {}

        # FK-safe order: the category link table BEFORE the category table,
        # and both before the plans they reference. Purges leaked test tarif
        # categories (test-cat-*, "Duplicate Root", …) so the subscription
        # seeder recreates a clean ``root`` category.
        #
        # Then purge tax pollution (S85.4): the five sellable↔tax link tables
        # BEFORE the core ``vbwd_tax`` table they reference (FK-safe), so the
        # reset reseeds a clean canonical VAT. ``vbwd_tax`` is a CORE table, so
        # clearing it in core is fine; each link table is plugin/core-owned and
        # guarded by ``_table_exists`` (no-op when a plugin is disabled).
        for table in [
            "subscription_tarif_plan_category_plans",
            "subscription_tarif_plan_category",
            "subscription_tarif_plan",
            "subscription_addon",
            "vbwd_token_bundle",
            "subscription_tarif_plan_tax",
            "subscription_addon_tax",
            "shop_product_tax",
            "booking_resource_tax",
            "token_bundle_tax",
            "vbwd_tax",
        ]:
            if not self._table_exists(table):
                continue
            result = self.session.execute(text(f"DELETE FROM {table}"))
            counts[f"deleted_{table}"] = result.rowcount  # type: ignore[attr-defined]

        return counts

    def _run_catalog_clearers(self) -> dict:
        """Run registry catalog CLEARERS before core clears its own tables.

        Each plugin that owns a table referencing a core table registers a
        clearer to purge those rows first, keeping the subsequent core DELETEs
        FK-safe. No-op when nothing is registered (plugins disabled)."""
        from vbwd.services.demo_data_registry import run_catalog_clearers

        run_catalog_clearers(self.session)
        self.session.flush()
        return {}

    def _run_post_seed_hooks(self) -> dict:
        """Run registry post-seed hooks (e.g. the CMS backfill) after all
        catalog seeders. No-op when nothing is registered (plugins disabled)."""
        from vbwd.services.demo_data_registry import run_post_seed_hooks

        self.session.flush()
        return run_post_seed_hooks(self.session)

    def _seed_catalog(self) -> dict:
        """Insert demo token bundles (core); delegate plan/addon catalog to
        feature plugins via the demo-data registry."""
        from vbwd.models.token_bundle import TokenBundle
        from vbwd.services.demo_data_registry import run_catalog_seeders

        # Seed the canonical VAT FIRST so every catalog seeder (core token
        # bundles below + each plugin's sellables) can link it (S85.4). ``Tax``
        # is a core model, so core owns its seed (single source of truth).
        stats = self._seed_taxes()

        bundles = []
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
            bundles.append(bundle)

        self.session.flush()

        # Link the canonical VAT to the demo token bundles (core owns bundles),
        # so their price disclosure shows gross > net.
        from vbwd.services.demo_tax_linker import link_demo_tax

        stats["token_bundle_taxes_linked"] = link_demo_tax(self.session, bundles)

        stats["seeded_token_bundles"] = len(DEMO_TOKEN_BUNDLES)

        # Feature plugins (subscription plans/addons, shop, booking, ghrm, cms
        # pages/widgets/layouts) own their catalog; each contributes a seeder
        # through the demo-data registry. No-op when a plugin is disabled.
        stats.update(run_catalog_seeders(self.session))
        self.session.flush()
        return stats

    def _seed_taxes(self) -> dict:
        """Seed the canonical demo VAT into ``vbwd_tax`` (idempotent).

        Delegates to the core ``seed_taxes`` single source of truth so demo and
        prod share the same default VAT catalog. No-op for rows that already
        exist (operator edits survive).
        """
        from vbwd.services.tax_seeder import seed_taxes

        result = seed_taxes(self.session)
        return {"taxes_created": result.taxes_created}

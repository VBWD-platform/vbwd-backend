"""Unit specs for the unified ``flask reset-demo`` seeder (S88).

These cover the seeder's contracts WITHOUT a database:
  - the transactional clear step skips tables that are not present (no crash);
  - the demo-data registry runs catalog seeders and the new post-seed hooks,
    and is a no-op when nothing is registered (plugin disabled / agnostic).
"""
from unittest.mock import MagicMock

import pytest


# ── clear-step robustness (regression for the verified crash) ────────────────


class _FakeResult:
    rowcount = 0


def _seeder_with_inspector(present_tables):
    """Build a DemoSeeder whose session reports only ``present_tables`` as
    existing, recording the tables actually targeted by DELETE."""
    from vbwd.cli._demo_seeder import DemoSeeder

    deleted = []

    session = MagicMock()

    def _execute(clause):
        text = str(clause)
        # Simulate Postgres: DELETE FROM a missing relation raises (the crash).
        for table in (
            "vbwd_token_transaction",
            "vbwd_user_invoice",
            "subscription_record",
            "vbwd_user_token_balance",
            "vbwd_token_bundle_purchase",
            "subscription_addon_subscription",
            "vbwd_invoice_line_item",
            "vbwd_feature_usage",
            "vbwd_password_reset_token",
        ):
            if f"FROM {table}" in text:
                if table not in present_tables:
                    raise RuntimeError(f'relation "{table}" does not exist')
                deleted.append(table)
        return _FakeResult()

    session.execute.side_effect = _execute

    seeder = DemoSeeder(session)
    # The seeder asks an inspector whether each table exists before deleting.
    seeder._table_exists = lambda table: table in present_tables  # type: ignore[attr-defined]
    return seeder, deleted


def test_clear_transactional_skips_absent_table():
    """A table that is not present must be skipped, not crash the reset."""
    # vbwd_token_transaction absent — the historical crash table.
    present = {"vbwd_user_invoice", "subscription_record", "vbwd_user_token_balance"}
    seeder, deleted = _seeder_with_inspector(present)

    seeder._clear_transactional_data()

    assert "vbwd_token_transaction" not in deleted
    # present tables that are in the clear list still get deleted
    assert "subscription_record" in deleted


def test_clear_transactional_no_tables_present_is_noop():
    """With no tables present at all, the clear step deletes nothing and does
    not raise."""
    seeder, deleted = _seeder_with_inspector(set())
    seeder._clear_transactional_data()
    assert deleted == []


# ── catalog clear-step (tarif categories must be purged of leaked test data) ──


def _catalog_seeder(present_tables):
    """Build a DemoSeeder whose session reports only ``present_tables`` as
    existing, recording the catalog tables actually targeted by DELETE."""
    from vbwd.cli._demo_seeder import DemoSeeder

    deleted = []
    session = MagicMock()

    def _execute(clause):
        text = str(clause)
        for table in (
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
        ):
            if f"FROM {table}" in text:
                deleted.append(table)
        return _FakeResult()

    session.execute.side_effect = _execute
    seeder = DemoSeeder(session)
    seeder._table_exists = lambda table: table in present_tables  # type: ignore[attr-defined]
    return seeder, deleted


def test_clear_catalog_deletes_tarif_categories_and_link_table():
    """Leaked tarif categories (and their plan links) must be purged so the
    subscription seeder can recreate a clean ``root`` category."""
    present = {
        "subscription_tarif_plan",
        "subscription_addon",
        "vbwd_token_bundle",
        "subscription_tarif_plan_category",
        "subscription_tarif_plan_category_plans",
    }
    seeder, deleted = _catalog_seeder(present)

    seeder._clear_catalog()

    assert "subscription_tarif_plan_category" in deleted
    assert "subscription_tarif_plan_category_plans" in deleted
    # Link table must be deleted BEFORE the category table (FK-safe order).
    assert deleted.index("subscription_tarif_plan_category_plans") < deleted.index(
        "subscription_tarif_plan_category"
    )


def test_clear_catalog_skips_absent_category_tables():
    """When the category tables are not present (plugin disabled), the catalog
    clear is a no-op for them and does not crash."""
    present = {"vbwd_token_bundle"}
    seeder, deleted = _catalog_seeder(present)

    seeder._clear_catalog()

    assert "subscription_tarif_plan_category" not in deleted
    assert "subscription_tarif_plan_category_plans" not in deleted
    assert "vbwd_token_bundle" in deleted


# ── catalog clear-step (tax pollution must be purged, S85.4) ──────────────────

_SELLABLE_TAX_LINK_TABLES = [
    "subscription_tarif_plan_tax",
    "subscription_addon_tax",
    "shop_product_tax",
    "booking_resource_tax",
    "token_bundle_tax",
]


def test_clear_catalog_purges_tax_links_and_taxes_when_present():
    """S85.4: the five sellable↔tax link tables AND ``vbwd_tax`` are purged so
    reset-demo reseeds a clean canonical VAT (test pollution gone)."""
    present = {
        "subscription_tarif_plan",
        "subscription_addon",
        "vbwd_token_bundle",
        "vbwd_tax",
        *_SELLABLE_TAX_LINK_TABLES,
    }
    seeder, deleted = _catalog_seeder(present)

    seeder._clear_catalog()

    for link_table in _SELLABLE_TAX_LINK_TABLES:
        assert link_table in deleted
    assert "vbwd_tax" in deleted


def test_clear_catalog_purges_tax_links_before_vbwd_tax():
    """FK-safe order: each sellable↔tax link table is cleared BEFORE the core
    ``vbwd_tax`` table they reference."""
    present = {"vbwd_tax", *_SELLABLE_TAX_LINK_TABLES}
    seeder, deleted = _catalog_seeder(present)

    seeder._clear_catalog()

    for link_table in _SELLABLE_TAX_LINK_TABLES:
        assert deleted.index(link_table) < deleted.index("vbwd_tax")


def test_clear_catalog_skips_absent_tax_tables():
    """When tax tables are absent (plugins disabled / not migrated) the clear is
    a no-op for them and does not crash."""
    present = {"vbwd_token_bundle"}
    seeder, deleted = _catalog_seeder(present)

    seeder._clear_catalog()

    for link_table in _SELLABLE_TAX_LINK_TABLES:
        assert link_table not in deleted
    assert "vbwd_tax" not in deleted


# ── registry wiring ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_registry():
    from vbwd.services import demo_data_registry

    demo_data_registry.clear_demo_data_hooks()
    yield
    demo_data_registry.clear_demo_data_hooks()


def test_run_catalog_seeders_invokes_each_hook():
    from vbwd.services import demo_data_registry

    session = MagicMock()
    calls = []
    demo_data_registry.register_catalog_seeder(lambda s: calls.append(("a", s)))
    demo_data_registry.register_catalog_seeder(lambda s: calls.append(("b", s)))

    demo_data_registry.run_catalog_seeders(session)

    assert [name for name, _ in calls] == ["a", "b"]
    assert all(passed_session is session for _, passed_session in calls)


def test_run_catalog_seeders_noop_when_none_registered():
    from vbwd.services import demo_data_registry

    # No hook registered (every plugin disabled) — must be a silent no-op.
    demo_data_registry.run_catalog_seeders(MagicMock())  # must not raise


def test_run_post_seed_hooks_invokes_each_hook():
    from vbwd.services import demo_data_registry

    session = MagicMock()
    calls = []
    demo_data_registry.register_post_seed_hook(lambda s: calls.append(s))

    demo_data_registry.run_post_seed_hooks(session)

    assert calls == [session]


def test_run_post_seed_hooks_noop_when_none_registered():
    from vbwd.services import demo_data_registry

    demo_data_registry.run_post_seed_hooks(MagicMock())  # must not raise


def test_clear_demo_data_hooks_clears_post_seed_hooks():
    from vbwd.services import demo_data_registry

    calls = []
    demo_data_registry.register_post_seed_hook(lambda s: calls.append(s))
    demo_data_registry.clear_demo_data_hooks()
    demo_data_registry.run_post_seed_hooks(MagicMock())
    assert calls == []

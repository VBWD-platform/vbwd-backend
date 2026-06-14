"""End-to-end integration spec for the unified ``flask reset-demo`` (S88).

Runs the real ``DemoSeeder.run()`` against the live test database with all
plugins enabled (their ``on_enable`` registered every catalog seeder + the CMS
backfill post-seed hook), then asserts that a representative row from every
vertical exists AND that key CMS pages resolve as unified ``cms_post`` rows
(i.e. the backfill ran).

Requires the full plugin schema to be present (migrated). When a required table
is absent the test skips rather than failing — keeping it cold-start safe and
honest about what it verifies.
"""
import pytest
from sqlalchemy import inspect


REQUIRED_TABLES = [
    "vbwd_token_bundle",
    "subscription_tarif_plan",
    "shop_product",
    "booking_resource",
    "ghrm_software_package",
    "cms_page",
    "cms_post",
]


@pytest.fixture
def seeded(app):
    """Run the full demo seed once and yield the active session."""
    from vbwd.extensions import db
    from vbwd.cli._demo_seeder import DemoSeeder

    with app.app_context():
        inspector = inspect(db.session.get_bind())
        missing = [t for t in REQUIRED_TABLES if not inspector.has_table(t)]
        if missing:
            pytest.skip(f"plugin schema not present: missing {missing}")
        DemoSeeder(db.session).run()
        yield db.session


def test_every_vertical_catalog_seeded(seeded):
    from vbwd.models.token_bundle import TokenBundle
    from plugins.subscription.subscription.models import TarifPlan
    from plugins.shop.shop.models.product import Product
    from plugins.booking.booking.models.resource import BookableResource
    from plugins.ghrm.src.models.ghrm_software_package import GhrmSoftwarePackage

    assert seeded.query(TokenBundle).count() >= 1
    assert seeded.query(TarifPlan).count() >= 1
    assert seeded.query(Product).count() >= 1
    assert seeded.query(BookableResource).count() >= 1
    assert seeded.query(GhrmSoftwarePackage).count() >= 1


def test_demo_sellables_carry_canonical_vat(seeded):
    """S85.4: a representative demo plan/addon/product/bundle/resource carries a
    linked tax with rate 19 so the price disclosure shows gross > net."""
    from decimal import Decimal

    from vbwd.models.token_bundle import TokenBundle
    from plugins.subscription.subscription.models import TarifPlan, AddOn
    from plugins.shop.shop.models.product import Product
    from plugins.booking.booking.models.resource import BookableResource

    def _has_standard_vat(sellable) -> bool:
        return any(tax.rate == Decimal("19.00") for tax in sellable.taxes)

    plan = seeded.query(TarifPlan).filter_by(slug="pro").first()
    assert plan is not None and _has_standard_vat(plan)

    addon = seeded.query(AddOn).filter_by(slug="priority-support").first()
    assert addon is not None and _has_standard_vat(addon)

    product = seeded.query(Product).filter_by(slug="wireless-headphones-pro").first()
    assert product is not None and _has_standard_vat(product)

    bundle = seeded.query(TokenBundle).first()
    assert bundle is not None and _has_standard_vat(bundle)

    resource = seeded.query(BookableResource).filter_by(slug="dr-smith").first()
    assert resource is not None and _has_standard_vat(resource)


def test_no_tax_pollution_after_reset(seeded):
    """No integration-test tax pollution (``_Updated`` / ``VAT_DUP_`` /
    ``_INUSE``) survives a reset-demo — only the clean canonical catalog."""
    from vbwd.models.tax import Tax

    polluted = (
        seeded.query(Tax)
        .filter(
            Tax.code.like("%_Updated")
            | Tax.code.like("VAT_DUP_%")
            | Tax.code.like("%_INUSE%")
            | Tax.name.like("%_Updated")
        )
        .count()
    )
    assert polluted == 0


def test_key_cms_pages_resolve_as_unified_posts(seeded):
    """The backfill (post-seed hook) folded the seeded pages into cms_post."""
    from plugins.cms.src.repositories.post_repository import PostRepository

    post_repo = PostRepository(seeded)
    for slug in ("shop", "booking", "shop-cart", "ghrm-software-catalogue"):
        assert (
            post_repo.find_by_type_and_slug("page", slug) is not None
        ), f"expected unified cms_post(page) for '{slug}'"


def test_root_tarif_category_resolves_with_active_plans(seeded):
    """After the full seed, the ``root`` tarif category exists and has at least
    one linked active plan (so ``/tarifs`` renders plans), and no leaked
    ``test-cat-*`` categories remain."""
    from plugins.subscription.subscription.repositories import (
        tarif_plan_category_repository,
    )
    from plugins.subscription.subscription.models import TarifPlanCategory

    TarifPlanCategoryRepository = (
        tarif_plan_category_repository.TarifPlanCategoryRepository
    )

    category_repo = TarifPlanCategoryRepository(seeded)
    root = category_repo.find_by_slug("root")
    assert root is not None, "expected a 'root' tarif category after reset-demo"
    active_linked = [plan for plan in root.tarif_plans if plan.is_active]
    assert len(active_linked) >= 1

    leaked = (
        seeded.query(TarifPlanCategory)
        .filter(TarifPlanCategory.slug.like("test-cat-%"))
        .count()
    )
    assert leaked == 0, "leaked test-cat-* categories must be purged by reset-demo"


def test_reset_demo_is_idempotent(app):
    """A second full run does not raise or duplicate token bundles."""
    from vbwd.extensions import db
    from vbwd.cli._demo_seeder import DemoSeeder
    from vbwd.models.token_bundle import TokenBundle

    with app.app_context():
        inspector = inspect(db.session.get_bind())
        if not inspector.has_table("vbwd_token_bundle"):
            pytest.skip("core schema not present")
        DemoSeeder(db.session).run()
        DemoSeeder(db.session).run()
        # token bundles are cleared + reseeded each run → exactly the 3 demo set
        assert db.session.query(TokenBundle).count() == 3

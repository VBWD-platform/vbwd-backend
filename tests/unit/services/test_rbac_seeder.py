"""Unit tests for the core RBAC default seeder — Sprint S38.

These tests exercise ``seed_default_rbac`` against an in-memory SQLite
session (real SQLAlchemy models, no Postgres) so the idempotency and
upsert semantics are verified end-to-end without a live DB. Plugin
permission collection is exercised via an injected fake ``plugin_manager``
(DI) — never importing a real plugin, keeping core agnostic.
"""
import pytest

from vbwd.extensions import db
from vbwd.models.role import Role, Permission, role_permissions
from vbwd.routes.admin.access import CORE_PERMISSIONS
from vbwd.services.permission_catalog import collect_permission_catalog
from vbwd.services.rbac_seeder import seed_default_rbac, RbacSeedResult


CORE_PERMISSION_KEYS = {permission["key"] for permission in CORE_PERMISSIONS}


class FakePlugin:
    """Minimal stand-in for a BasePlugin exposing admin_permissions."""

    def __init__(self, name, admin_permissions):
        self._name = name
        self.admin_permissions = admin_permissions

    @property
    def metadata(self):
        class _Meta:
            name = self._name

        meta = _Meta()
        meta.name = self._name
        return meta


class FakePluginManager:
    """Injectable plugin manager returning a fixed set of enabled plugins."""

    def __init__(self, enabled_plugins):
        self._enabled_plugins = enabled_plugins

    def get_enabled_plugins(self):
        return list(self._enabled_plugins)


def _wipe_rbac(session):
    """Remove all role/permission rows so each test starts clean."""
    session.execute(role_permissions.delete())
    session.query(Role).delete()
    session.query(Permission).delete()
    session.commit()


@pytest.fixture
def session(app):
    """Real (Postgres) db.session inside an app context, RBAC wiped clean.

    The seeder relies on real upsert + commit semantics, so a MagicMock
    cannot exercise it; we use the live test DB and isolate by wiping the
    RBAC tables before and after each test.
    """
    with app.app_context():
        _wipe_rbac(db.session)
        try:
            yield db.session
        finally:
            db.session.rollback()
            _wipe_rbac(db.session)


class TestSeedDefaultRbacRoles:
    """The 3 default system roles."""

    def test_creates_three_system_roles_with_correct_slugs(self, session):
        seed_default_rbac(session)

        slugs = {role.slug for role in session.query(Role).all()}
        assert slugs == {"super_admin", "admin", "user"}

    def test_all_default_roles_are_system(self, session):
        seed_default_rbac(session)

        for role in session.query(Role).all():
            assert role.is_system is True

    def test_super_admin_has_wildcard(self, session):
        seed_default_rbac(session)

        super_admin = session.query(Role).filter_by(slug="super_admin").one()
        assert [p.name for p in super_admin.permissions] == ["*"]

    def test_admin_has_all_core_permissions(self, session):
        seed_default_rbac(session)

        admin = session.query(Role).filter_by(slug="admin").one()
        assert {p.name for p in admin.permissions} == CORE_PERMISSION_KEYS

    def test_user_has_no_permissions(self, session):
        seed_default_rbac(session)

        user = session.query(Role).filter_by(slug="user").one()
        assert list(user.permissions) == []


class TestSeedDefaultRbacPermissions:
    """The permission catalog sync."""

    def test_every_core_permission_key_becomes_a_permission_row(self, session):
        seed_default_rbac(session)

        names = {p.name for p in session.query(Permission).all()}
        assert CORE_PERMISSION_KEYS.issubset(names)

    def test_plugin_admin_permissions_synced_via_injected_manager(self, session):
        plugin = FakePlugin(
            "shop",
            [
                {"key": "shop.products.view", "label": "View", "group": "Shop"},
                {"key": "shop.products.manage", "label": "Manage", "group": "Shop"},
            ],
        )
        manager = FakePluginManager([plugin])

        seed_default_rbac(session, plugin_manager=manager)

        names = {p.name for p in session.query(Permission).all()}
        assert "shop.products.view" in names
        assert "shop.products.manage" in names


class TestSeedDefaultRbacIdempotency:
    """Re-running the seeder is a no-op."""

    def test_second_run_creates_nothing_new(self, session):
        seed_default_rbac(session)
        result = seed_default_rbac(session)

        assert isinstance(result, RbacSeedResult)
        assert result.roles_created == 0
        assert result.permissions_created == 0
        assert session.query(Role).count() == 3

    def test_first_run_reports_three_roles_created(self, session):
        result = seed_default_rbac(session, plugin_manager=FakePluginManager([]))

        assert result.roles_created == 3
        # Core permission keys plus the wildcard ("*") used by super_admin.
        assert result.permissions_created == len(CORE_PERMISSION_KEYS) + 1


class TestSeedDefaultRbacGuards:
    """Liskov / safety guards."""

    def test_does_not_overwrite_non_system_role_of_same_slug(self, session):
        custom = Role(
            name="Custom Admin",
            slug="admin",
            description="hand-made",
            is_system=False,
        )
        session.add(custom)
        session.commit()

        seed_default_rbac(session)

        admin = session.query(Role).filter_by(slug="admin").one()
        assert admin.is_system is False
        assert admin.name == "Custom Admin"
        assert list(admin.permissions) == []

    def test_fail_fast_on_malformed_catalog_entry(self, session):
        plugin = FakePlugin("broken", [{"label": "No key", "group": "Broken"}])
        manager = FakePluginManager([plugin])

        with pytest.raises(ValueError):
            seed_default_rbac(session, plugin_manager=manager)


class TestSharedCatalogCollector:
    """Route and seeder read the same catalog source (DRY)."""

    def test_collector_returns_core_keys(self):
        catalog = collect_permission_catalog(plugin_manager=FakePluginManager([]))
        assert "core" in catalog
        keys = {entry["key"] for entry in catalog["core"]}
        assert keys == CORE_PERMISSION_KEYS

    def test_collector_includes_injected_plugin_permissions(self):
        plugin = FakePlugin(
            "shop",
            [{"key": "shop.products.view", "label": "View", "group": "Shop"}],
        )
        manager = FakePluginManager([plugin])

        catalog = collect_permission_catalog(plugin_manager=manager)
        assert catalog["shop"][0]["key"] == "shop.products.view"

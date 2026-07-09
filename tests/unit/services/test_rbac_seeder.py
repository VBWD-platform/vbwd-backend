"""Unit tests for the core RBAC default seeder — Sprint S38.

These tests exercise ``seed_default_rbac`` against an in-memory SQLite
session (real SQLAlchemy models, no Postgres) so the idempotency and
upsert semantics are verified end-to-end without a live DB. Plugin
permission collection is exercised via an injected fake ``plugin_manager``
(DI) — never importing a real plugin, keeping core agnostic.
"""
import pytest

from vbwd.extensions import db
from vbwd.models.role import Role, Permission, role_permissions, user_roles
from vbwd.models.user_access_level import (
    AccessLevel,
    user_access_level_permissions,
    user_user_access_levels,
)
from vbwd.routes.admin.access import CORE_PERMISSIONS, CORE_USER_PERMISSIONS
from vbwd.services.permission_catalog import (
    collect_permission_catalog,
    collect_user_permission_catalog,
)
from vbwd.services.rbac_seeder import (
    DEFAULT_USER_ACCESS_LEVELS,
    seed_default_rbac,
    RbacSeedResult,
)


CORE_PERMISSION_KEYS = {permission["key"] for permission in CORE_PERMISSIONS}
CORE_USER_PERMISSION_KEYS = {permission["key"] for permission in CORE_USER_PERMISSIONS}


class FakePlugin:
    """Minimal stand-in for a BasePlugin exposing admin + user permissions."""

    def __init__(self, name, admin_permissions=None, user_permissions=None):
        self._name = name
        self.admin_permissions = admin_permissions or []
        self.user_permissions = user_permissions or []

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
    # Clear the user↔role link first: since S39 seeds an admin-with-role at
    # app startup, a leftover user_roles row otherwise makes DELETE FROM
    # vbwd_admin_role violate vbwd_user_admin_role_role_id_fkey.
    session.execute(user_roles.delete())
    session.execute(role_permissions.delete())
    session.execute(user_access_level_permissions.delete())
    session.execute(user_user_access_levels.delete())
    session.query(AccessLevel).delete()
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
    """The 2 default admin system roles."""

    def test_creates_two_admin_system_roles_with_correct_slugs(self, session):
        seed_default_rbac(session)

        slugs = {role.slug for role in session.query(Role).all()}
        assert slugs == {"super_admin", "admin"}

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

    def test_no_redundant_user_role_is_seeded(self, session):
        seed_default_rbac(session)

        assert session.query(Role).filter_by(slug="user").first() is None


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
        assert session.query(Role).count() == 2

    def test_first_run_reports_two_roles_created(self, session):
        result = seed_default_rbac(session, plugin_manager=FakePluginManager([]))

        assert result.roles_created == 2
        # The seeder creates one Permission row per catalog key plus the
        # wildcard ("*") plus the core user-facing permissions (S52 — e.g.
        # ``manage_api`` — so an admin can grant them to user access levels).
        # The catalog is core permissions + the data-exchange sales perms
        # auto-derived from the registered core exchangers (S46.1); derive the
        # expected count from the same single sources so this stays accurate.
        from vbwd.routes.admin.access import CORE_USER_PERMISSIONS

        catalog = collect_permission_catalog(plugin_manager=FakePluginManager([]))
        catalog_keys = {
            entry["key"] for entries in catalog.values() for entry in entries
        }
        user_permission_keys = {entry["key"] for entry in CORE_USER_PERMISSIONS}
        expected = catalog_keys | {"*"} | user_permission_keys
        assert result.permissions_created == len(expected)


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


class TestSeedDefaultUserAccessLevels:
    """The 4 default user access levels (fe-user permission tiers)."""

    _EXPECTED_SLUGS = {"new", "logged-in", "subscribed-basic", "subscribed-pro"}

    def test_creates_four_default_user_access_levels(self, session):
        seed_default_rbac(session)

        slugs = {level.slug for level in session.query(AccessLevel).all()}
        assert slugs == self._EXPECTED_SLUGS

    def test_all_default_levels_are_system(self, session):
        seed_default_rbac(session)

        for level in session.query(AccessLevel).all():
            assert level.is_system is True

    def test_first_run_reports_four_levels_created(self, session):
        result = seed_default_rbac(session)

        assert result.user_access_levels_created == 4

    def test_second_run_creates_zero_levels(self, session):
        seed_default_rbac(session)
        result = seed_default_rbac(session)

        assert result.user_access_levels_created == 0
        assert session.query(AccessLevel).count() == 4

    def test_linked_plan_slug_is_seeded(self, session):
        seed_default_rbac(session)

        logged_in = session.query(AccessLevel).filter_by(slug="logged-in").one()
        assert logged_in.linked_plan_slug == "free"

    def test_pre_existing_level_is_not_modified(self, session):
        """Create-only / prod-safe: a hand-edited level is left untouched."""
        permission = Permission(
            id=__import__("uuid").uuid4(),
            name="user.profile.view",
            resource="user.profile",
            action="view",
            description="View profile",
        )
        session.add(permission)
        existing = AccessLevel(
            name="Custom Logged In",
            slug="logged-in",
            description="operator edited",
            is_system=False,
            linked_plan_slug="custom-plan",
        )
        existing.permissions.append(permission)
        session.add(existing)
        session.commit()

        seed_default_rbac(session)

        reloaded = session.query(AccessLevel).filter_by(slug="logged-in").one()
        assert reloaded.name == "Custom Logged In"
        assert reloaded.description == "operator edited"
        assert reloaded.is_system is False
        assert reloaded.linked_plan_slug == "custom-plan"
        assert [p.name for p in reloaded.permissions] == ["user.profile.view"]

    def test_missing_permission_keys_are_skipped_no_crash(self, session):
        """Core-only install: absent permission keys resolve to nothing."""
        # With NO plugins enabled, none of the level permission keys exist in
        # the catalog, so a core-only install must create every level WITHOUT
        # raising and with no grants.
        seed_default_rbac(session, plugin_manager=FakePluginManager([]))

        new_level = session.query(AccessLevel).filter_by(slug="new").one()
        assert list(new_level.permissions) == []

    def test_only_resolvable_permission_subset_is_attached(self, session):
        """A level attaches the keys that exist and silently skips the rest."""
        permission = Permission(
            id=__import__("uuid").uuid4(),
            name="user.profile.view",
            resource="user.profile",
            action="view",
            description="View profile",
        )
        session.add(permission)
        session.commit()

        # Empty plugin manager → no plugin declares cms.content.view, so only
        # the pre-existing user.profile.view resolves for the "new" level.
        seed_default_rbac(session, plugin_manager=FakePluginManager([]))

        new_level = session.query(AccessLevel).filter_by(slug="new").one()
        # "new" references user.profile.view (now present) + cms.content.view
        # (absent) — only the resolvable one is attached.
        assert [p.name for p in new_level.permissions] == ["user.profile.view"]

    def test_default_levels_constant_covers_the_four_slugs(self):
        slugs = {level["slug"] for level in DEFAULT_USER_ACCESS_LEVELS}
        assert slugs == self._EXPECTED_SLUGS

    def test_operator_json_override_replaces_shipped_defaults(
        self, session, tmp_path, monkeypatch
    ):
        """A var/ JSON override is seeded in place of the shipped defaults."""
        import json

        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "user_access_levels.json").write_text(
            json.dumps(
                [
                    {
                        "slug": "operator-tier",
                        "name": "Operator Tier",
                        "description": "operator defined",
                        "linked_plan_slug": "custom",
                        "permissions": [],
                    }
                ]
            )
        )
        monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))

        result = seed_default_rbac(session)

        assert result.user_access_levels_created == 1
        slugs = {level.slug for level in session.query(AccessLevel).all()}
        assert slugs == {"operator-tier"}


class TestUserPermissionCatalog:
    """The user-facing permission catalog (core + plugin ``user_permissions``)."""

    def test_empty_manager_returns_only_core(self):
        catalog = collect_user_permission_catalog(plugin_manager=FakePluginManager([]))
        assert set(catalog) == {"core"}
        assert {e["key"] for e in catalog["core"]} == CORE_USER_PERMISSION_KEYS

    def test_none_manager_without_app_context_degrades_to_core_only(self, monkeypatch):
        # No injected manager and no resolvable Flask app context → degrade to
        # core-only WITHOUT raising. Simulate a torn-down context deterministically
        # (a bare ``plugin_manager=None`` call would otherwise pick up any app
        # context another test leaked into the shared session).
        class _NoContextProxy:
            def __getattr__(self, name):
                raise RuntimeError("Working outside of application context.")

        monkeypatch.setattr("flask.current_app", _NoContextProxy())
        catalog = collect_user_permission_catalog(plugin_manager=None)
        assert set(catalog) == {"core"}

    def test_includes_plugin_user_permissions(self):
        plugin = FakePlugin(
            "subscription",
            user_permissions=[
                {"key": "user.profile.view", "label": "View", "group": "User"},
            ],
        )
        catalog = collect_user_permission_catalog(
            plugin_manager=FakePluginManager([plugin])
        )
        assert catalog["subscription"][0]["key"] == "user.profile.view"

    def test_plugin_without_user_permissions_attribute_does_not_crash(self):
        class _BarePlugin:
            @property
            def metadata(self):
                class _Meta:
                    name = "bare"

                return _Meta()

        catalog = collect_user_permission_catalog(
            plugin_manager=FakePluginManager([_BarePlugin()])
        )
        assert set(catalog) == {"core"}

    def test_admin_route_helper_returns_same_shape(self, session):
        """Guard the ``/admin/access/user-permissions`` contract after refactor."""
        from vbwd.routes.admin.access import _get_all_user_permissions

        result = _get_all_user_permissions()
        assert isinstance(result, dict)
        assert "core" in result
        assert {e["key"] for e in result["core"]} == CORE_USER_PERMISSION_KEYS


class TestSeedPluginUserPermissions:
    """Plugin ``user_permissions`` are upserted so level grants resolve."""

    def test_plugin_user_permission_becomes_a_permission_row(self, session):
        plugin = FakePlugin(
            "subscription",
            user_permissions=[
                {"key": "user.profile.view", "label": "View", "group": "User"},
            ],
        )
        seed_default_rbac(session, plugin_manager=FakePluginManager([plugin]))

        assert (
            session.query(Permission).filter_by(name="user.profile.view").first()
            is not None
        )

    def test_logged_in_level_holds_plugin_user_permission_after_seeding(self, session):
        plugin = FakePlugin(
            "subscription",
            user_permissions=[
                {"key": "user.profile.view", "label": "V", "group": "User"},
                {"key": "user.profile.manage", "label": "M", "group": "User"},
                {"key": "subscription.plans.view", "label": "P", "group": "Sub"},
                {"key": "subscription.invoices.view", "label": "I", "group": "Sub"},
                {"key": "subscription.tokens.view", "label": "T", "group": "Sub"},
            ],
        )
        seed_default_rbac(session, plugin_manager=FakePluginManager([plugin]))

        logged_in = session.query(AccessLevel).filter_by(slug="logged-in").one()
        names = {p.name for p in logged_in.permissions}
        assert "user.profile.view" in names
        assert "subscription.plans.view" in names
        # The 6th key (cms.content.view) is declared by no plugin here, so it is
        # skipped leniently — the level still seeds with the 5 resolvable grants.
        assert names == {
            "user.profile.view",
            "user.profile.manage",
            "subscription.plans.view",
            "subscription.invoices.view",
            "subscription.tokens.view",
        }


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

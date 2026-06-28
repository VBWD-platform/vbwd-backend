"""Tests for DependencyResolver (S108.1 + S108.2)."""
import pytest
from unittest.mock import MagicMock

from vbwd.plugins.base import PluginStatus
from vbwd.plugins.dependency_resolver import DependencyResolver
from vbwd.plugins.errors import PluginDependencyError


def _make_plugin(name, version="26.6", dependencies=None, status=PluginStatus.ENABLED):
    plugin = MagicMock()
    plugin.metadata.name = name
    plugin.metadata.version = version
    plugin.metadata.dependencies = dependencies or []
    plugin.status = status
    return plugin


def _registry(plugins):
    """Return a get_plugin callable backed by a name -> plugin dict."""
    table = {plugin.metadata.name: plugin for plugin in plugins}
    return lambda name: table.get(name)


class TestDependencyResolverCheck:
    """DependencyResolver.check raises PluginDependencyError on unmet deps."""

    def test_satisfied_version_passes(self):
        email = _make_plugin("email", version="26.7")
        dependent = _make_plugin("booking", dependencies=["email>=26.7"])
        resolver = DependencyResolver()

        # Should not raise.
        resolver.check(dependent, _registry([email, dependent]))

    def test_version_too_old_raises(self):
        email = _make_plugin("email", version="26.6")
        dependent = _make_plugin("booking", dependencies=["email>=26.7"])
        resolver = DependencyResolver()

        with pytest.raises(PluginDependencyError) as excinfo:
            resolver.check(dependent, _registry([email, dependent]))
        message = str(excinfo.value)
        assert "email>=26.7" in message
        assert "26.6" in message

    def test_dependency_missing_raises(self):
        dependent = _make_plugin("booking", dependencies=["email>=26.7"])
        resolver = DependencyResolver()

        with pytest.raises(PluginDependencyError) as excinfo:
            resolver.check(dependent, _registry([dependent]))
        assert "not enabled" in str(excinfo.value)

    def test_dependency_not_enabled_raises(self):
        email = _make_plugin("email", status=PluginStatus.INITIALIZED)
        dependent = _make_plugin("booking", dependencies=["email"])
        resolver = DependencyResolver()

        with pytest.raises(PluginDependencyError) as excinfo:
            resolver.check(dependent, _registry([email, dependent]))
        assert "not enabled" in str(excinfo.value)

    def test_bare_dependency_ignores_version(self):
        email = _make_plugin("email", version="1.0.0")
        dependent = _make_plugin("booking", dependencies=["email"])
        resolver = DependencyResolver()

        # Bare name: any version satisfies.
        resolver.check(dependent, _registry([email, dependent]))

    def test_plugin_dependency_error_is_value_error(self):
        assert issubclass(PluginDependencyError, ValueError)


class TestDependencyResolverDescribe:
    """describe returns the admin-API dependency descriptor objects."""

    def test_describe_satisfied(self):
        email = _make_plugin("email", version="26.7")
        dependent = _make_plugin("booking", dependencies=["email>=26.7"])
        resolver = DependencyResolver()

        descriptors = resolver.describe(dependent, _registry([email, dependent]))
        assert descriptors == [
            {
                "name": "email",
                "specifier": ">=26.7",
                "installed_version": "26.7",
                "satisfied": True,
            }
        ]

    def test_describe_bare_dependency(self):
        email = _make_plugin("email", version="26.6")
        dependent = _make_plugin("booking", dependencies=["email"])
        resolver = DependencyResolver()

        descriptors = resolver.describe(dependent, _registry([email, dependent]))
        assert descriptors[0]["specifier"] == ""
        assert descriptors[0]["installed_version"] == "26.6"
        assert descriptors[0]["satisfied"] is True

    def test_describe_missing_dependency(self):
        dependent = _make_plugin("booking", dependencies=["email>=26.7"])
        resolver = DependencyResolver()

        descriptors = resolver.describe(dependent, _registry([dependent]))
        assert descriptors[0]["installed_version"] is None
        assert descriptors[0]["satisfied"] is False

    def test_describe_version_mismatch(self):
        email = _make_plugin("email", version="26.6")
        dependent = _make_plugin("booking", dependencies=["email>=26.7"])
        resolver = DependencyResolver()

        descriptors = resolver.describe(dependent, _registry([email, dependent]))
        assert descriptors[0]["satisfied"] is False
        assert descriptors[0]["installed_version"] == "26.6"


class TestDependencyResolverEnableOrder:
    """enable_order topologically sorts plugins by declared dependencies."""

    def test_dependency_before_dependent(self):
        email = _make_plugin("email", dependencies=[])
        booking = _make_plugin("booking", dependencies=["email"])
        resolver = DependencyResolver()

        # Dependent listed before its dependency in the input.
        order = resolver.enable_order([booking, email])
        assert order.index("email") < order.index("booking")

    def test_chain_order(self):
        email = _make_plugin("email", dependencies=[])
        subscription = _make_plugin("subscription", dependencies=["email"])
        tarot = _make_plugin("tarot", dependencies=["subscription"])
        resolver = DependencyResolver()

        order = resolver.enable_order([tarot, subscription, email])
        assert order.index("email") < order.index("subscription")
        assert order.index("subscription") < order.index("tarot")

    def test_external_dependency_ignored_for_ordering(self):
        # booking depends on email which is NOT in the given set.
        booking = _make_plugin("booking", dependencies=["email"])
        resolver = DependencyResolver()

        order = resolver.enable_order([booking])
        assert order == ["booking"]

    def test_cycle_does_not_crash(self):
        first = _make_plugin("first", dependencies=["second"])
        second = _make_plugin("second", dependencies=["first"])
        resolver = DependencyResolver()

        order = resolver.enable_order([first, second])
        assert set(order) == {"first", "second"}

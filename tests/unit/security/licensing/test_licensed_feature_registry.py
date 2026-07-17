"""The licensed-feature registry collects plugin declarations, names none itself."""
from vbwd.registries.licensed_feature_registry import (
    collect_licensed_features,
    is_licensable_feature,
)


class _FakePlugin:
    def __init__(self, features):
        self.licensed_features = tuple(features)


class _FakePluginManager:
    def __init__(self, plugins):
        self._plugins = plugins

    def get_enabled_plugins(self):
        return list(self._plugins)


def test_declared_feature_is_seen():
    manager = _FakePluginManager([_FakePlugin(("marketplace",))])
    assert collect_licensed_features(plugin_manager=manager) == ["marketplace"]
    assert is_licensable_feature("marketplace", plugin_manager=manager) is True


def test_unlisted_feature_is_false():
    manager = _FakePluginManager([_FakePlugin(("marketplace",))])
    assert is_licensable_feature("analytics", plugin_manager=manager) is False


def test_features_are_deduplicated_across_plugins():
    manager = _FakePluginManager(
        [_FakePlugin(("marketplace",)), _FakePlugin(("marketplace", "analytics"))]
    )
    assert collect_licensed_features(plugin_manager=manager) == [
        "marketplace",
        "analytics",
    ]


def test_no_manager_returns_empty():
    assert collect_licensed_features(plugin_manager=None) == []

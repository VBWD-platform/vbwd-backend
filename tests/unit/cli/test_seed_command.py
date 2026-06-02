"""Specs for the ``flask seed [PLUGIN_NAME]...`` CLI (S30 slice 0).

The command discovers enabled plugins via the plugin manager (NOT the
filesystem), calls each plugin's optional ``populate()`` method, and falls
back to running its ``populate_db.py`` via ``runpy`` with exit-code
propagation when no ``populate()`` is defined. Strict mode (default) fails
on the first plugin error; ``--best-effort`` continues and reports at the
end. ``--json`` emits a machine-readable summary.
"""
import json
from unittest.mock import MagicMock, patch

import pytest


class _StubPlugin:
    """A plugin double with an optional ``populate()`` method."""

    def __init__(self, name, populate_result=None, raises=None):
        self.metadata = MagicMock()
        self.metadata.name = name
        self._populate_result = populate_result or {
            "created": 0,
            "skipped": 0,
            "errors": [],
        }
        self._raises = raises
        self.populate_calls = 0

    def populate(self):
        self.populate_calls += 1
        if self._raises is not None:
            raise self._raises
        return self._populate_result


class _LegacyPlugin:
    """A plugin double WITHOUT a ``populate()`` method (legacy fallback)."""

    def __init__(self, name):
        self.metadata = MagicMock()
        self.metadata.name = name
        self.populate_calls = 0


@pytest.fixture
def stub_plugins(app):
    """Install a deterministic set of enabled plugins on the app manager and
    record a marker-writer double. Returns the dict of name -> stub."""
    plugins = {
        "meinchat": _StubPlugin("meinchat", {"created": 3, "skipped": 0, "errors": []}),
        "subscription": _StubPlugin(
            "subscription", {"created": 1, "skipped": 0, "errors": []}
        ),
    }
    app.plugin_manager.get_enabled_plugins = MagicMock(
        return_value=list(plugins.values())
    )
    app.plugin_manager.get_plugin = MagicMock(
        side_effect=lambda name: plugins.get(name)
    )
    return plugins


def _invoke(runner, args):
    from vbwd.cli.seed import seed_command

    return runner.invoke(seed_command, args)


def test_seed_all_calls_every_enabled_plugin_populate(app, runner, stub_plugins):
    """Spec 1: ``seed all`` calls each enabled plugin's populate() once."""
    with patch("vbwd.cli.seed.write_seed_marker"):
        result = _invoke(runner, ["all"])
    assert result.exit_code == 0
    assert stub_plugins["meinchat"].populate_calls == 1
    assert stub_plugins["subscription"].populate_calls == 1


def test_seed_named_plugin_calls_only_that_plugin(app, runner, stub_plugins):
    """Spec 2: ``seed meinchat`` calls only meinchat's populate()."""
    with patch("vbwd.cli.seed.write_seed_marker"):
        result = _invoke(runner, ["meinchat"])
    assert result.exit_code == 0
    assert stub_plugins["meinchat"].populate_calls == 1
    assert stub_plugins["subscription"].populate_calls == 0


def test_unknown_plugin_exits_2(app, runner, stub_plugins):
    """Spec 3: an unknown plugin name exits 2 with a clear message."""
    with patch("vbwd.cli.seed.write_seed_marker"):
        result = _invoke(runner, ["not_a_plugin"])
    assert result.exit_code == 2
    assert "unknown plugin" in result.output.lower()
    assert "not_a_plugin" in result.output


def test_populate_raising_exits_1_in_strict_mode(app, runner, stub_plugins):
    """Spec 4: a populate() raising -> exit 1 in --strict (the default)."""
    stub_plugins["meinchat"]._raises = RuntimeError("boom")
    with patch("vbwd.cli.seed.write_seed_marker"):
        result = _invoke(runner, ["all"])
    assert result.exit_code == 1
    assert "meinchat" in result.output


def test_populate_raising_exits_0_in_best_effort_but_listed(app, runner, stub_plugins):
    """Spec 5: in --best-effort a raising populate() -> exit 0, but the JSON
    summary records the error."""
    stub_plugins["meinchat"]._raises = RuntimeError("boom")
    with patch("vbwd.cli.seed.write_seed_marker"):
        result = _invoke(runner, ["all", "--best-effort", "--json"])
    assert result.exit_code == 0
    summary = json.loads(result.output)
    meinchat_entry = next(
        entry for entry in summary["plugins"] if entry["name"] == "meinchat"
    )
    assert meinchat_entry["ok"] is False
    assert meinchat_entry["errors"]


def test_plugin_without_populate_falls_back_to_populate_db(app, runner):
    """Spec 6: a plugin without populate() runs populate_db.py via runpy and
    propagates its exit code."""
    plugin = _LegacyPlugin("legacy")
    app.plugin_manager.get_enabled_plugins = MagicMock(return_value=[plugin])
    app.plugin_manager.get_plugin = MagicMock(
        side_effect=lambda name: plugin if name == "legacy" else None
    )
    with patch("vbwd.cli.seed.write_seed_marker"), patch(
        "vbwd.cli.seed.run_populate_db_module", return_value=0
    ) as mock_runner:
        result = _invoke(runner, ["legacy"])
    assert result.exit_code == 0
    mock_runner.assert_called_once_with("legacy")


def test_plugin_with_no_seed_source_is_noop_success(app, runner):
    """Spec 6b: a plugin with neither populate() nor populate_db.py is a no-op
    success (ok=True), so ``seed all`` in strict mode still passes."""
    from vbwd.cli.seed import NO_SEED_SOURCE

    plugin = _LegacyPlugin("no_seed")
    app.plugin_manager.get_enabled_plugins = MagicMock(return_value=[plugin])
    app.plugin_manager.get_plugin = MagicMock(
        side_effect=lambda name: plugin if name == "no_seed" else None
    )
    with patch("vbwd.cli.seed.write_seed_marker"), patch(
        "vbwd.cli.seed.run_populate_db_module", return_value=NO_SEED_SOURCE
    ):
        result = _invoke(runner, ["all", "--json"])
    assert result.exit_code == 0
    summary = json.loads(result.output)
    assert summary["plugins"][0]["ok"] is True


def test_json_summary_has_documented_shape(app, runner, stub_plugins):
    """Spec 7: ``--json`` emits valid JSON with the documented shape."""
    with patch("vbwd.cli.seed.write_seed_marker"):
        result = _invoke(runner, ["all", "--json"])
    summary = json.loads(result.output)
    assert "plugins" in summary
    for entry in summary["plugins"]:
        assert set(entry.keys()) >= {"name", "ok", "created", "errors"}
        assert isinstance(entry["ok"], bool)
        assert isinstance(entry["created"], int)
        assert isinstance(entry["errors"], list)


def test_disabled_plugins_skipped_silently_on_seed_all(app, runner, stub_plugins):
    """Spec 8: ``seed all`` only iterates enabled plugins; a disabled plugin
    (absent from get_enabled_plugins) is never touched and does not crash."""
    # A "disabled" plugin would raise if touched; it is simply not enabled.
    disabled = _StubPlugin("disabled_one", raises=RuntimeError("should not run"))

    def get_plugin(name):
        if name == "disabled_one":
            return disabled
        return stub_plugins.get(name)

    app.plugin_manager.get_plugin = MagicMock(side_effect=get_plugin)
    with patch("vbwd.cli.seed.write_seed_marker"):
        result = _invoke(runner, ["all"])
    assert result.exit_code == 0
    assert disabled.populate_calls == 0


def test_reset_clears_marker_for_named_plugin(app, runner, stub_plugins):
    """Spec 9: ``seed meinchat --reset`` clears the marker (no populate)."""
    with patch("vbwd.cli.seed.write_seed_marker"), patch(
        "vbwd.cli.seed.clear_seed_marker"
    ) as mock_clear:
        result = _invoke(runner, ["meinchat", "--reset"])
    assert result.exit_code == 0
    mock_clear.assert_called_once_with("meinchat")
    assert stub_plugins["meinchat"].populate_calls == 0


def test_successful_populate_writes_marker(app, runner, stub_plugins):
    """Spec 10: a successful populate() writes a seed marker for the plugin."""
    with patch("vbwd.cli.seed.write_seed_marker") as mock_write:
        result = _invoke(runner, ["meinchat"])
    assert result.exit_code == 0
    mock_write.assert_called_once_with("meinchat")

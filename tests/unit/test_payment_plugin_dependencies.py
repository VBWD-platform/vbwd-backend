"""S07 oracle — payment plugins that call ``resolve_subscription_lifecycle``
must declare ``subscription`` in their ``PluginMetadata.dependencies``.

PluginManager.enable_plugin already enforces declared dependencies at
runtime (raises ValueError if a dep isn't enabled), but only if the
plugin *declared* the dep in the first place. This oracle catches the
"implicit dep" smell: code uses the subscription port but metadata
declares an empty deps list.

To stay green, a plugin must either:
  * NOT import / call ``resolve_subscription_lifecycle``, OR
  * declare ``dependencies=[..., "subscription", ...]``.
"""
import os
import re

import pytest


PAYMENT_PLUGINS = [
    "stripe",
    "paypal",
    "yookassa",
    "conekta",
    "mercado_pago",
    "truemoney",
    "toss_payments",
    "promptpay",
    "c2p2",
    "token_payment",
]


def _backend_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def _plugin_calls_subscription_lifecycle(plugin_name: str) -> bool:
    """Return True if any .py file under the plugin references the
    subscription lifecycle port."""
    plugin_dir = os.path.join(_backend_root(), "plugins", plugin_name)
    if not os.path.isdir(plugin_dir):
        return False
    needle = re.compile(r"\b(resolve_subscription_lifecycle|subscription_lifecycle\.)")
    for dirpath, _dirs, files in os.walk(plugin_dir):
        if "__pycache__" in dirpath or "/tests/" in dirpath:
            continue
        for filename in files:
            if not filename.endswith(".py"):
                continue
            with open(os.path.join(dirpath, filename)) as handle:
                if needle.search(handle.read()):
                    return True
    return False


def _plugin_is_installed(plugin_name: str) -> bool:
    """True if the plugin source is present in ``plugins/<name>/__init__.py``.

    CI runs that clone only a subset of plugins (the lean matrix) skip
    this test for plugins that aren't installed.
    """
    return os.path.isfile(
        os.path.join(_backend_root(), "plugins", plugin_name, "__init__.py")
    )


def _plugin_declared_dependencies(plugin_name: str) -> list[str]:
    """Parse the plugin's ``__init__.py`` and return the declared
    ``PluginMetadata.dependencies`` list (string-literal extraction)."""
    init = os.path.join(_backend_root(), "plugins", plugin_name, "__init__.py")
    with open(init) as handle:
        source = handle.read()
    # find the dependencies=[...] expression
    match = re.search(r"dependencies\s*=\s*\[([^\]]*)\]", source)
    if not match:
        return []
    inner = match.group(1)
    return re.findall(r"[\"']([A-Za-z0-9_]+)[\"']", inner)


@pytest.mark.parametrize("plugin_name", PAYMENT_PLUGINS)
def test_plugin_dep_matches_subscription_usage(plugin_name):
    """If a plugin calls ``resolve_subscription_lifecycle``, it MUST declare
    ``subscription`` in ``PluginMetadata.dependencies``."""
    if not _plugin_is_installed(plugin_name):
        pytest.skip(f"plugin '{plugin_name}' not installed in this CI matrix")
    uses_subscription = _plugin_calls_subscription_lifecycle(plugin_name)
    declared = _plugin_declared_dependencies(plugin_name)
    if uses_subscription:
        assert "subscription" in declared, (
            f"plugins/{plugin_name}/ calls resolve_subscription_lifecycle "
            f"but its PluginMetadata.dependencies = {declared!r}. "
            "Add 'subscription' to the dependencies list so PluginManager "
            "refuses to enable this plugin when subscription is disabled."
        )
    else:
        # Sanity: plugins that don't use the port should not need the dep.
        # We don't *force* deps=[], but we note when the audit list is
        # tighter than expected.
        if "subscription" in declared:
            # informational, not a failure — could be a future-proof dep
            pass

"""S06 oracle — ``vbwd/app.py`` must not name any plugin as a string literal.

The boot-time plugin enable + blueprint registration in ``app.py`` used to
special-case ``"analytics"`` by string. S06 replaces that with:

  - default-enable list read from ``plugins/plugins.json.dist`` (so any
    plugin can be a default, just by editing the dist file).
  - admin-blueprint registration that iterates EVERY enabled plugin and
    calls ``get_admin_blueprint()`` (the base default returns ``None`` so
    plugins without an admin BP just no-op).

After S06: zero plugin-name string literals in ``app.py``.
"""
import ast
import os

import pytest

KNOWN_PLUGINS = [
    "analytics",
    "booking",
    "cms",
    "ghrm",
    "stripe",
    "paypal",
    "yookassa",
    "conekta",
    "mercado_pago",
    "truemoney",
    "toss_payments",
    "promptpay",
    "subscription",
    "taro",
    "meinchat",
    "chat",
    "shop",
    "discount",
    "checkout",
    "c2p2",
    "token_payment",
    "email",
    "shipping_flat_rate",
    "mailchimp",
    "demoplugin",
]


def _app_py_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    backend = os.path.dirname(os.path.dirname(here))
    return os.path.join(backend, "vbwd", "app.py")


@pytest.mark.parametrize("plugin_name", KNOWN_PLUGINS)
def test_app_py_does_not_hardcode_plugin_name(plugin_name):
    """``vbwd/app.py`` source must not contain ``"<plugin_name>"`` as a
    string-literal AST constant (comments/docstrings are fine).

    Until S06 lands this fails on ``"analytics"`` (and on ``"booking"`` if
    S01 didn't run). After S06, it stays green forever.
    """
    with open(_app_py_path()) as handle:
        source = handle.read()
    tree = ast.parse(source, filename=_app_py_path())
    offenders: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == plugin_name:
            offenders.append(node.lineno)
    assert not offenders, (
        f'vbwd/app.py contains plugin name "{plugin_name}" as a string '
        f"literal at line(s) {offenders}. Move the default-enable list to "
        "plugins/plugins.json.dist; iterate plugins generically for "
        "blueprint registration."
    )

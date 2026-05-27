"""S11 oracle — SDK adapters MUST raise ``UnsupportedOperationError`` for
structurally-unsupported operations, not return ``SDKResponse(success=False)``.

Returning a soft failure for a structural inability looks like a transient
error to callers (could trigger retry storms / spurious refunds). Raising
makes the contract honest and lets a single shared helper translate the
exception into a 501 Not Implemented at the route layer.

Permanent grep oracle: no ``SDKResponse(success=False, error="…does not
support…")`` / ``…do not support…`` pattern anywhere in plugin SDK
adapter files.
"""
import os
import re

import pytest

from vbwd.sdk.errors import UnsupportedOperationError


def _backend_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def _sdk_adapter_files() -> list[str]:
    plugins_root = os.path.join(_backend_root(), "plugins")
    matches: list[str] = []
    for dirpath, _dirs, files in os.walk(plugins_root):
        if "__pycache__" in dirpath or "/tests/" in dirpath:
            continue
        for filename in files:
            if filename.endswith("sdk_adapter.py"):
                matches.append(os.path.join(dirpath, filename))
    return matches


def test_no_sdk_returns_success_false_for_structural_inability():
    """If a provider structurally cannot do an op, the adapter raises
    ``UnsupportedOperationError`` instead of returning ``success=False``."""
    # Look for the actual smell: `SDKResponse(success=False, error="…does
    # not support…")`. Excludes comments/docstrings (they don't construct
    # SDKResponse).
    smell = re.compile(
        r"SDKResponse\s*\(\s*success\s*=\s*False[^)]*(?:not\s+support|do\s+not\s+support|does\s+not\s+support)",
        re.IGNORECASE | re.DOTALL,
    )
    findings: list[str] = []
    for adapter_path in _sdk_adapter_files():
        with open(adapter_path) as handle:
            source = handle.read()
        for match in smell.finditer(source):
            line_number = source.count("\n", 0, match.start()) + 1
            relative = os.path.relpath(adapter_path, _backend_root())
            findings.append(f"{relative}:{line_number} — {match.group(0)[:80]}")
    assert not findings, (
        "SDK adapters must raise UnsupportedOperationError for structurally "
        "unsupported operations, not return SDKResponse(success=False) "
        f"with a 'does not support' error string. Found {len(findings)} site(s):\n  - "
        + "\n  - ".join(findings)
    )


def test_unsupported_operation_error_is_importable():
    """One canonical home for the exception so every adapter and helper
    can import it from the same place."""
    assert issubclass(UnsupportedOperationError, Exception)


# Per-adapter contract checks ------------------------------------------------


def _plugin_installed(plugin_name: str) -> bool:
    """Skip per-plugin contract tests when the plugin isn't cloned in CI."""
    return os.path.isdir(os.path.join(_backend_root(), "plugins", plugin_name))


def _build_mercado_adapter():
    from plugins.mercado_pago.mercado_pago.sdk_adapter import MercadoPagoSDKAdapter
    from vbwd.sdk.interface import SDKConfig

    return MercadoPagoSDKAdapter(SDKConfig(api_key="test"), country="AR")


def _build_truemoney_adapter():
    from plugins.truemoney.truemoney.sdk_adapter import TrueMoneySDKAdapter
    from vbwd.sdk.interface import SDKConfig

    return TrueMoneySDKAdapter(
        SDKConfig(api_key="test"),
        merchant_id="m",
        api_url="https://example.test",
    )


@pytest.mark.parametrize(
    "plugin_name, factory",
    [
        ("mercado_pago", _build_mercado_adapter),
        ("truemoney", _build_truemoney_adapter),
    ],
)
def test_release_authorization_raises_when_unsupported(plugin_name, factory):
    """``release_authorization`` raises ``UnsupportedOperationError`` on
    providers that structurally don't support it."""
    if not _plugin_installed(plugin_name):
        pytest.skip(f"plugin '{plugin_name}' not installed in this CI matrix")
    adapter = factory()
    with pytest.raises(UnsupportedOperationError):
        adapter.release_authorization("dummy-intent")


def test_mercado_pago_capture_payment_raises():
    """Mercado Pago captures happen on user redirect; the adapter must
    flag this as structurally unsupported."""
    if not _plugin_installed("mercado_pago"):
        pytest.skip("plugin 'mercado_pago' not installed in this CI matrix")
    adapter = _build_mercado_adapter()
    with pytest.raises(UnsupportedOperationError):
        adapter.capture_payment("dummy-intent")

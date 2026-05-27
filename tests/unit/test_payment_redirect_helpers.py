"""S21 — redirect-URL helper contract tests + dedup oracle."""
import os
import re
from unittest.mock import MagicMock

from vbwd.plugins.payment_route_helpers import (
    build_provider_redirect_urls,
    resolve_frontend_base,
)


def _fake_request(headers: dict, host_url: str = "https://api.example.com/"):
    request = MagicMock()
    request.headers.get.side_effect = lambda key, default="": headers.get(key, default)
    request.host_url = host_url
    return request


def test_resolve_frontend_base_uses_origin_when_present():
    assert (
        resolve_frontend_base(_fake_request({"Origin": "https://app.example.com"}))
        == "https://app.example.com"
    )


def test_resolve_frontend_base_falls_back_to_referer():
    assert (
        resolve_frontend_base(
            _fake_request({"Referer": "https://app.example.com/pay/stripe/start"})
        )
        == "https://app.example.com"
    )


def test_resolve_frontend_base_falls_back_to_host_url():
    assert (
        resolve_frontend_base(_fake_request({}, "https://api.example.com/"))
        == "https://api.example.com"
    )


def test_build_redirect_urls_web_no_query():
    success, cancel = build_provider_redirect_urls(
        _fake_request({"Origin": "https://app.example.com"}), "paypal"
    )
    assert success == "https://app.example.com/pay/paypal/success"
    assert cancel == "https://app.example.com/pay/paypal/cancel"


def test_build_redirect_urls_web_with_session_query():
    success, _ = build_provider_redirect_urls(
        _fake_request({"Origin": "https://app.example.com"}),
        "yookassa",
        success_query="?session_id={{session_id}}",
    )
    assert (
        success
        == "https://app.example.com/pay/yookassa/success?session_id={{session_id}}"
    )


def test_build_redirect_urls_ios_deep_link():
    success, cancel = build_provider_redirect_urls(
        _fake_request(
            {"Origin": "https://app.example.com", "X-Client-Platform": "iOS"}
        ),
        "stripe",
        success_query="?session_id={CHECKOUT_SESSION_ID}",
        ios_deep_link=True,
    )
    assert success == "vbwd://stripe-callback/success?session_id={CHECKOUT_SESSION_ID}"
    assert cancel == "vbwd://stripe-callback/cancel"


def test_build_redirect_urls_ios_not_used_when_flag_off():
    """A provider that doesn't opt in to iOS deep links never returns a deep link."""
    success, _ = build_provider_redirect_urls(
        _fake_request(
            {"Origin": "https://app.example.com", "X-Client-Platform": "iOS"}
        ),
        "yookassa",
        ios_deep_link=False,
    )
    assert success.startswith("https://app.example.com/")


# ── Oracle: payment plugin route files don't reimplement the helper ──────


def _payment_routes_files() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    backend = os.path.dirname(os.path.dirname(here))
    plugins_dir = os.path.join(backend, "plugins")
    matches: list[str] = []
    for provider in ("stripe", "paypal", "yookassa"):
        path = os.path.join(plugins_dir, provider, provider, "routes.py")
        if os.path.isfile(path):
            matches.append(path)
    return matches


def test_payment_plugins_use_resolve_frontend_base_helper():
    """Every payment plugin that derives ``frontend_base`` does so via the
    shared helper, not by re-inlining the Origin/Referer/host_url chain."""
    smell = re.compile(
        r"request\.headers\.get\([\"']Origin[\"']\)\s*\n\s*or\s*request\.headers\.get\([\"']Referer",
        re.MULTILINE,
    )
    offenders: list[str] = []
    for path in _payment_routes_files():
        with open(path) as handle:
            content = handle.read()
        if smell.search(content):
            offenders.append(os.path.relpath(path))
    assert not offenders, (
        "Payment plugins must use vbwd.plugins.payment_route_helpers."
        "resolve_frontend_base / build_provider_redirect_urls instead of "
        "re-inlining the Origin/Referer/host_url chain. Offenders:\n  - "
        + "\n  - ".join(offenders)
    )

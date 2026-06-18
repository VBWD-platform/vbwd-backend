"""S99.0 — the core payment webhook denominates in the CONFIGURED currency.

The legacy default was a hard-coded ``"USD"`` literal. The contract (S99) is
one billing currency = the ``default_currency`` core setting; runtime paths must
read that, never a literal. This test sets the setting to ``USD`` then ``EUR``
and asserts the dispatched ``PaymentCapturedEvent`` carries whatever was
configured — proving no literal fallback remains.

The route is auth+permission gated and dispatches through the container's event
dispatcher; both are stubbed so the test exercises only the currency
resolution. The settings store is pointed at a throwaway ``VBWD_VAR_DIR``.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vbwd.events.domain import EventResult


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Throwaway ``VBWD_VAR_DIR`` + no DB catalog provider for each test.

    A prior test that built the Flask ``app`` may leave a DB-backed currency
    catalog provider wired globally; clearing it keeps the settings update here
    on a structural-only validation path (the ``app`` fixture re-wires its own
    provider inside its app context, so the route still validates against the
    real catalog when it runs).
    """
    from vbwd.services.core_settings_store import register_currency_catalog_provider

    monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
    register_currency_catalog_provider(None)
    yield tmp_path
    register_currency_catalog_provider(None)


def _authenticate_as_admin(app, monkeypatch):
    """Stub the auth + permission chain so the route runs without a real user."""
    admin_user = SimpleNamespace(
        status=SimpleNamespace(value="ACTIVE"),
        is_admin=True,
        has_permission=lambda permission: True,
    )
    fake_repo = MagicMock()
    fake_repo.find_by_id.return_value = admin_user
    fake_auth_service = MagicMock()
    fake_auth_service.verify_token.return_value = "admin-user-id"
    monkeypatch.setattr(
        "vbwd.middleware.auth.UserRepository", lambda session: fake_repo
    )
    monkeypatch.setattr(
        "vbwd.middleware.auth.AuthService", lambda user_repository: fake_auth_service
    )


def _capture_dispatched_event(app):
    """Replace the dispatcher with a capturing stub; return the captured holder."""
    captured = {}

    def _emit(event):
        captured["event"] = event
        return EventResult(success=True, data={"items_activated": {}})

    dispatcher = MagicMock()
    dispatcher.emit.side_effect = _emit
    app.container.event_dispatcher = MagicMock(return_value=dispatcher)
    return captured


@pytest.mark.parametrize("configured_currency", ["USD", "EUR"])
def test_webhook_uses_configured_default_currency(
    app, client, monkeypatch, configured_currency
):
    from vbwd.services.core_settings_store import update_core_settings

    update_core_settings(
        {
            "active_currencies": ["EUR", "USD"],
            "default_currency": configured_currency,
        }
    )
    _authenticate_as_admin(app, monkeypatch)
    captured = _capture_dispatched_event(app)

    response = client.post(
        "/api/v1/webhooks/payment",
        headers={"Authorization": "Bearer test-token"},
        # No "currency" key — the route must fall back to the setting, not "USD".
        json={
            "invoice_id": "00000000-0000-0000-0000-000000000001",
            "payment_reference": "PAY-1",
            "amount": "29.00",
        },
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert captured["event"].currency == configured_currency

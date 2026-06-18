"""Auth guard for the core payment webhook (S90 DoD #7 / G5).

The core ``POST /api/v1/webhooks/payment`` is ONLY the admin "manually mark an
invoice as paid" tool — real providers use their own signature-validated plugin
webhooks. Previously it took NO auth and NO signature, so anyone could forge a
paid event. It is now gated behind ``@require_auth`` + ``@require_permission``;
an unauthenticated POST must be rejected (401) before any invoice mutation.

The ``/payment/test`` reachability probe stays public (static ok, no state).
"""


class TestPaymentWebhookRequiresAuth:
    def test_post_payment_webhook_without_auth_is_rejected(self, client):
        """No Authorization header → 401 (the @require_auth gate), never 200."""
        response = client.post(
            "/api/v1/webhooks/payment",
            json={
                "invoice_id": "00000000-0000-0000-0000-000000000000",
                "payment_reference": "PAY-FORGED",
                "amount": "29.00",
                "currency": "USD",
            },
        )
        assert response.status_code == 401

    def test_payment_test_probe_stays_public(self, client):
        """The reachability probe is unchanged: public, static ok."""
        response = client.post("/api/v1/webhooks/payment/test")
        assert response.status_code == 200
        assert response.get_json()["status"] == "ok"


class TestPaymentWebhookOracleClassification:
    def test_payment_webhook_is_authorization_gated(self):
        """The route now carries requires_auth + a required_permission marker,
        so the route-exposure oracle classifies it as protected (no longer in
        the public mutation allow-list)."""
        from vbwd.routes.webhooks import payment_webhook
        from vbwd.security.route_audit import inspect_view

        requires_auth, required_permission, requires_admin, _ = inspect_view(
            payment_webhook
        )
        assert requires_auth is True
        assert required_permission is not None or requires_admin is True

    def test_payment_webhook_not_in_public_mutation_allowlist(self):
        from vbwd.security.route_audit import PUBLIC_MUTATION_ALLOWLIST

        assert "/api/v1/webhooks/payment" not in PUBLIC_MUTATION_ALLOWLIST
        # The reachability probe stays allow-listed.
        assert "/api/v1/webhooks/payment/test" in PUBLIC_MUTATION_ALLOWLIST

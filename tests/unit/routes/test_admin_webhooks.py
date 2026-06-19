"""DB-backed route tests for the admin outbound-webhook API.

Like ``test_admin_llm_connections``: hits the live session through the
``client`` fixture with mocked auth, and an autouse fixture keeps the two
webhook tables empty per test. No real network — the deliver path is exercised
by patching the service's HTTP transport. Also asserts the event-bus relay
enqueues on a real ``event_bus.publish``.
"""
from unittest.mock import patch
from uuid import uuid4

import pytest

from tests.fixtures.access import (
    make_user_no_permissions,
    make_user_with_permissions,
)

BASE = "/api/v1/admin/webhooks"
PERM = "settings.manage"


def _auth_headers():
    return {"Authorization": "Bearer valid"}


def _mock_auth(mock_repo_cls, mock_auth_cls, user):
    mock_repo_cls.return_value.find_by_id.return_value = user
    mock_auth_cls.return_value.verify_token.return_value = str(uuid4())


@pytest.fixture(autouse=True)
def clean_tables(app):
    from vbwd.extensions import db
    from vbwd.models.webhook_delivery import WebhookDelivery
    from vbwd.models.webhook_subscription import WebhookSubscription

    with app.app_context():
        WebhookSubscription.__table__.create(bind=db.engine, checkfirst=True)
        WebhookDelivery.__table__.create(bind=db.engine, checkfirst=True)
        db.session.query(WebhookDelivery).delete()
        db.session.query(WebhookSubscription).delete()
        db.session.commit()
    yield
    with app.app_context():
        db.session.query(WebhookDelivery).delete()
        db.session.query(WebhookSubscription).delete()
        db.session.commit()


def _admin(mock_repo_cls, mock_auth_cls):
    _mock_auth(mock_repo_cls, mock_auth_cls, make_user_with_permissions(PERM))


class TestPermissions:
    def test_list_unauthenticated(self, client):
        assert client.get(BASE).status_code == 401

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_forbidden_without_permission(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _mock_auth(mock_repo_cls, mock_auth_cls, make_user_no_permissions())
        assert client.get(BASE, headers=_auth_headers()).status_code == 403


class TestCrud:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_generates_secret_and_lists(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _admin(mock_repo_cls, mock_auth_cls)
        created = client.post(
            BASE,
            headers=_auth_headers(),
            json={"url": "https://example.com/hook", "events": ["payment.captured"]},
        )
        assert created.status_code == 201
        webhook = created.get_json()["webhook"]
        assert webhook["secret"]
        assert webhook["status"] == "active"
        assert webhook["events"] == ["payment.captured"]

        listed = client.get(BASE, headers=_auth_headers())
        assert listed.status_code == 200
        body = listed.get_json()
        assert body["total"] == 1
        assert set(body) == {"webhooks", "total", "page", "per_page"}

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_rejects_bad_url(self, mock_repo_cls, mock_auth_cls, client):
        _admin(mock_repo_cls, mock_auth_cls)
        resp = client.post(
            BASE, headers=_auth_headers(), json={"url": "ftp://x", "events": ["*"]}
        )
        assert resp.status_code == 400

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_get_update_toggle_delete(self, mock_repo_cls, mock_auth_cls, client):
        _admin(mock_repo_cls, mock_auth_cls)
        webhook_id = client.post(
            BASE,
            headers=_auth_headers(),
            json={"url": "https://example.com/hook", "events": ["*"]},
        ).get_json()["webhook"]["id"]

        got = client.get(f"{BASE}/{webhook_id}", headers=_auth_headers())
        assert got.status_code == 200
        assert "delivery_history" in got.get_json()["webhook"]

        updated = client.put(
            f"{BASE}/{webhook_id}",
            headers=_auth_headers(),
            json={"events": ["payment.refunded"]},
        )
        assert updated.get_json()["webhook"]["events"] == ["payment.refunded"]

        toggled = client.post(f"{BASE}/{webhook_id}/toggle", headers=_auth_headers())
        assert toggled.get_json()["webhook"]["status"] == "inactive"

        deleted = client.delete(f"{BASE}/{webhook_id}", headers=_auth_headers())
        assert deleted.status_code == 200
        assert (
            client.get(f"{BASE}/{webhook_id}", headers=_auth_headers()).status_code
            == 404
        )

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_event_types_catalog(self, mock_repo_cls, mock_auth_cls, client):
        _admin(mock_repo_cls, mock_auth_cls)
        resp = client.get(f"{BASE}/event-types", headers=_auth_headers())
        assert resp.status_code == 200
        values = {item["value"] for item in resp.get_json()["event_types"]}
        assert "*" in values
        assert "payment.captured" in values
        assert "webhook.test" in values


class TestDeliveryAndRelay:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_test_endpoint_delivers_with_mocked_http(
        self, mock_repo_cls, mock_auth_cls, client, app
    ):
        _admin(mock_repo_cls, mock_auth_cls)
        webhook_id = client.post(
            BASE,
            headers=_auth_headers(),
            json={"url": "https://example.com/hook", "events": ["*"]},
        ).get_json()["webhook"]["id"]

        from vbwd.webhooks.outbound_service import WebhookHttpResponse

        with patch(
            "vbwd.webhooks.outbound_service._default_http_post",
            return_value=WebhookHttpResponse(200, "ok"),
        ) as posted:
            resp = client.post(f"{BASE}/{webhook_id}/test", headers=_auth_headers())
        assert resp.status_code == 200
        delivery = resp.get_json()["delivery"]
        assert delivery["status"] == "success"
        assert delivery["event_type"] == "webhook.test"
        assert posted.called

    def test_event_bus_publish_enqueues_pending_delivery(self, app):
        """A real bus publish must create a pending delivery for a matcher."""
        from vbwd.extensions import db
        from vbwd.events.bus import event_bus
        from vbwd.models.webhook_delivery import STATUS_PENDING, WebhookDelivery
        from vbwd.models.webhook_subscription import WebhookSubscription

        with app.app_context():
            subscription = WebhookSubscription(
                id=uuid4(),
                url="https://example.com/hook",
                secret="s",
                event_types=["payment.captured"],
                is_active=True,
                consecutive_failure_count=0,
            )
            db.session.add(subscription)
            db.session.commit()

        # The relay is subscribed at app construction; publishing now should
        # enqueue exactly one pending delivery.
        event_bus.publish("payment.captured", {"invoice_id": "abc"})

        with app.app_context():
            deliveries = db.session.query(WebhookDelivery).all()
            assert len(deliveries) == 1
            assert deliveries[0].status == STATUS_PENDING
            assert deliveries[0].event_type == "payment.captured"

    def test_failed_delivery_then_retry_scheduled(self, app):
        from datetime import datetime, timedelta
        from unittest.mock import patch as _patch

        from vbwd.extensions import db
        from vbwd.models.webhook_delivery import (
            DEFAULT_MAX_ATTEMPTS,
            STATUS_FAILED,
            STATUS_PENDING,
            WebhookDelivery,
        )
        from vbwd.models.webhook_subscription import WebhookSubscription
        from vbwd.repositories.webhook_delivery_repository import (
            WebhookDeliveryRepository,
        )
        from vbwd.repositories.webhook_subscription_repository import (
            WebhookSubscriptionRepository,
        )
        from vbwd.webhooks.outbound_service import (
            OutboundWebhookService,
            WebhookHttpResponse,
        )

        with app.app_context():
            subscription = WebhookSubscription(
                id=uuid4(),
                url="https://example.com/hook",
                secret="s",
                event_types=["*"],
                is_active=True,
                consecutive_failure_count=0,
            )
            db.session.add(subscription)
            db.session.commit()
            service = OutboundWebhookService(
                WebhookSubscriptionRepository(db.session),
                WebhookDeliveryRepository(db.session),
            )
            service.enqueue_for_event("anything", {})

            # All attempts return 500. Advance ``now`` past each scheduled
            # backoff so every retry is due; after max_attempts the delivery
            # is marked failed (and intermediate attempts stay pending).
            statuses = []
            with _patch(
                "vbwd.webhooks.outbound_service._default_http_post",
                return_value=WebhookHttpResponse(500, "boom"),
            ):
                for attempt in range(DEFAULT_MAX_ATTEMPTS):
                    now = datetime(2099, 1, 1) + timedelta(days=attempt)
                    service.deliver_due(now=now)
                    db.session.expire_all()
                    statuses.append(db.session.query(WebhookDelivery).one().status)

            # Intermediate attempts re-scheduled as pending; final = failed.
            assert statuses[0] == STATUS_PENDING
            delivery = db.session.query(WebhookDelivery).one()
            assert delivery.status == STATUS_FAILED
            assert delivery.attempt_count == DEFAULT_MAX_ATTEMPTS

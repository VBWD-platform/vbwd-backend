"""Unit tests for the outbound webhook system (core, agnostic).

No DB and no real network: repositories are ``MagicMock`` and the HTTP
transport is an injected fake. Covers signing, enqueue matching, backoff,
auto-disable, and status mapping in ``to_dict``.
"""
from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.webhook_delivery import (
    DEFAULT_MAX_ATTEMPTS,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SUCCESS,
    WebhookDelivery,
)
from vbwd.models.webhook_subscription import (
    AUTO_DISABLE_FAILURE_THRESHOLD,
    WebhookSubscription,
)
from vbwd.webhooks.outbound_service import (
    BACKOFF_BASE_SECONDS,
    OutboundWebhookService,
    WebhookHttpResponse,
)
from vbwd.webhooks.signing import compute_signature, verify_signature


class _RecordingHttp:
    """Fake HTTP transport that records calls and returns a scripted result."""

    def __init__(self, status_code=200, body="ok", raise_error=None):
        self.status_code = status_code
        self.body = body
        self.raise_error = raise_error
        self.calls = []

    def __call__(self, url, body, headers, timeout):
        self.calls.append((url, body, headers, timeout))
        if self.raise_error is not None:
            raise self.raise_error
        return WebhookHttpResponse(self.status_code, self.body)


def _make_subscription(event_types, active=True, url="https://example.com/hook"):
    subscription = WebhookSubscription(
        id=uuid4(),
        url=url,
        secret="topsecret",
        event_types=event_types,
        is_active=active,
        consecutive_failure_count=0,
    )
    return subscription


def _make_delivery(subscription, event_type="payment.captured", attempt_count=0):
    return WebhookDelivery(
        id=uuid4(),
        webhook_id=subscription.id,
        event_type=event_type,
        event_payload={"invoice_id": "abc"},
        status=STATUS_PENDING,
        attempt_count=attempt_count,
        max_attempts=DEFAULT_MAX_ATTEMPTS,
        created_at=datetime(2026, 1, 1, 12, 0, 0),
    )


def _service(subscription_repo=None, delivery_repo=None, http=None):
    subscription_repo = subscription_repo or MagicMock()
    delivery_repo = delivery_repo or MagicMock()
    # save returns the entity unchanged
    subscription_repo.save.side_effect = lambda entity, **_: entity
    delivery_repo.save.side_effect = lambda entity, **_: entity
    return (
        OutboundWebhookService(subscription_repo, delivery_repo, http_post=http),
        subscription_repo,
        delivery_repo,
    )


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------


def test_signature_is_deterministic_and_prefixed():
    sig = compute_signature("secret", b'{"a":1}')
    assert sig.startswith("sha256=")
    assert sig == compute_signature("secret", b'{"a":1}')


def test_signature_verifies_and_rejects_tampered_body():
    body = b'{"event":"x"}'
    sig = compute_signature("secret", body)
    assert verify_signature("secret", body, sig) is True
    assert verify_signature("secret", b'{"event":"y"}', sig) is False
    assert verify_signature("wrong", body, sig) is False


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------


def test_status_mapping_active_inactive_failed():
    active = _make_subscription(["*"], active=True)
    assert active.to_dict()["status"] == "active"

    inactive = _make_subscription(["*"], active=False)
    inactive.consecutive_failure_count = 0
    assert inactive.to_dict()["status"] == "inactive"

    failed = _make_subscription(["*"], active=False)
    failed.consecutive_failure_count = AUTO_DISABLE_FAILURE_THRESHOLD
    assert failed.to_dict()["status"] == "failed"


def test_subscription_to_dict_shape():
    subscription = _make_subscription(["payment.captured"], active=True)
    body = subscription.to_dict()
    assert set(body).issuperset(
        {"id", "url", "events", "status", "secret", "created_at", "last_triggered_at"}
    )
    assert body["events"] == ["payment.captured"]


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


def test_enqueue_creates_pending_delivery_per_matching_subscription():
    matching = _make_subscription(["payment.captured"])
    wildcard = _make_subscription(["*"])
    subscription_repo = MagicMock()
    subscription_repo.find_active_matching.return_value = [matching, wildcard]
    service, _, delivery_repo = _service(subscription_repo=subscription_repo)

    count = service.enqueue_for_event("payment.captured", {"invoice_id": "abc"})

    assert count == 2
    assert delivery_repo.save.call_count == 2
    saved = delivery_repo.save.call_args_list[0].args[0]
    assert saved.status == STATUS_PENDING
    assert saved.event_type == "payment.captured"
    # last_triggered_at updated on each subscription
    assert matching.last_triggered_at is not None


def test_enqueue_no_match_inserts_nothing():
    subscription_repo = MagicMock()
    subscription_repo.find_active_matching.return_value = []
    service, _, delivery_repo = _service(subscription_repo=subscription_repo)
    assert service.enqueue_for_event("nobody.listens", {}) == 0
    delivery_repo.save.assert_not_called()


def test_matches_event_name_and_wildcard():
    assert _make_subscription(["a.b", "*"]).matches_event("z.z") is True
    assert _make_subscription(["a.b"]).matches_event("a.b") is True
    assert _make_subscription(["a.b"]).matches_event("c.d") is False


# ---------------------------------------------------------------------------
# Delivery success / failure / backoff / auto-disable
# ---------------------------------------------------------------------------


def test_deliver_due_success_marks_success_and_resets_failures():
    subscription = _make_subscription(["*"])
    subscription.consecutive_failure_count = 2
    delivery = _make_delivery(subscription)
    subscription_repo = MagicMock()
    subscription_repo.find_by_id.return_value = subscription
    delivery_repo = MagicMock()
    delivery_repo.find_due.return_value = [delivery]
    http = _RecordingHttp(status_code=200, body="ok")
    service, _, _ = _service(subscription_repo, delivery_repo, http)

    attempted = service.deliver_due()

    assert attempted == 1
    assert delivery.status == STATUS_SUCCESS
    assert delivery.delivered_at is not None
    assert delivery.response_code == 200
    assert subscription.consecutive_failure_count == 0
    # signature header was sent
    _, _, headers, _ = http.calls[0]
    assert headers["X-VBWD-Signature"].startswith("sha256=")
    assert headers["X-VBWD-Event"] == "payment.captured"


def test_failure_schedules_backoff_then_fails_after_max():
    subscription = _make_subscription(["*"])
    delivery = _make_delivery(subscription)
    subscription_repo = MagicMock()
    subscription_repo.find_by_id.return_value = subscription
    delivery_repo = MagicMock()
    http = _RecordingHttp(status_code=500, body="boom")
    service, _, _ = _service(subscription_repo, delivery_repo, http)
    now = datetime(2026, 1, 1, 12, 0, 0)

    # First failure -> still pending, next_attempt_at scheduled with backoff
    service._attempt_delivery(delivery, subscription, now)
    assert delivery.status == STATUS_PENDING
    assert delivery.attempt_count == 1
    expected_first = now.timestamp() + BACKOFF_BASE_SECONDS * 2
    assert delivery.next_attempt_at.timestamp() == pytest.approx(expected_first)

    # Drive to the max; final attempt marks failed
    delivery.attempt_count = DEFAULT_MAX_ATTEMPTS - 1
    service._attempt_delivery(delivery, subscription, now)
    assert delivery.status == STATUS_FAILED
    assert delivery.next_attempt_at is None
    assert subscription.consecutive_failure_count == 1


def test_auto_disable_after_threshold_consecutive_failures():
    subscription = _make_subscription(["*"])
    subscription.consecutive_failure_count = AUTO_DISABLE_FAILURE_THRESHOLD - 1
    delivery = _make_delivery(subscription, attempt_count=DEFAULT_MAX_ATTEMPTS - 1)
    subscription_repo = MagicMock()
    delivery_repo = MagicMock()
    http = _RecordingHttp(status_code=503, body="down")
    service, _, _ = _service(subscription_repo, delivery_repo, http)

    service._attempt_delivery(delivery, subscription, datetime(2026, 1, 1))

    assert delivery.status == STATUS_FAILED
    assert subscription.consecutive_failure_count == AUTO_DISABLE_FAILURE_THRESHOLD
    assert subscription.is_active is False
    assert subscription.to_dict()["status"] == "failed"


def test_transport_error_is_recorded_not_raised():
    subscription = _make_subscription(["*"])
    delivery = _make_delivery(subscription)
    subscription_repo = MagicMock()
    subscription_repo.find_by_id.return_value = subscription
    delivery_repo = MagicMock()
    delivery_repo.find_due.return_value = [delivery]
    http = _RecordingHttp(raise_error=ConnectionError("refused"))
    service, _, _ = _service(subscription_repo, delivery_repo, http)

    # Must not raise out of the drain
    attempted = service.deliver_due()
    assert attempted == 1
    assert delivery.status == STATUS_PENDING
    assert "refused" in delivery.error


def test_create_rejects_non_http_url():
    service, _, _ = _service()
    with pytest.raises(ValueError):
        service.create("ftp://nope", ["*"])


def test_create_generates_secret_when_absent():
    service, subscription_repo, _ = _service()
    subscription = service.create("https://example.com/hook", ["*"])
    assert subscription.secret
    assert len(subscription.secret) >= 32

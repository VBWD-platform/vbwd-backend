"""S138.0 Inc 5 — the best-effort ``token.moved`` EventBus publish.

For non-critical consumers (notifications, analytics). Critical bookkeeping uses
the hook: the bus swallows subscriber exceptions (``vbwd/events/bus.py``), so a
failed mirror would leave core tokens moved and the error merely logged. The
event is convenience only.

Published AFTER the commit — a subscriber must never learn about a movement that
the database rolled back.
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.events import event_bus
from vbwd.models.enums import PurchaseStatus, TokenTransactionType
from vbwd.services.token_balance_hooks import (
    ITokenMovementHook,
    clear_token_movement_hooks,
    register_token_movement_hook,
)
from vbwd.services.token_service import TokenService

EVENT_NAME = "token.moved"


class RaisingHook(ITokenMovementHook):
    def on_token_moved(self, movement, session) -> None:
        raise RuntimeError("bookkeeping failed")


@pytest.fixture(autouse=True)
def _clean_hook_registry():
    clear_token_movement_hooks()
    yield
    clear_token_movement_hooks()


@pytest.fixture
def published():
    """Capture every ``token.moved`` payload, then unsubscribe."""
    events = []

    def _subscriber(event_name, data):
        events.append((event_name, data))

    event_bus.subscribe(EVENT_NAME, _subscriber)
    yield events
    event_bus.unsubscribe(EVENT_NAME, _subscriber)


@pytest.fixture
def session():
    return MagicMock()


def _service(session, balance_repo=None, purchase_repo=None):
    return TokenService(
        balance_repo=balance_repo or MagicMock(),
        transaction_repo=MagicMock(),
        purchase_repo=purchase_repo or MagicMock(),
        session=session,
    )


def _credit_ready_repo(balance=10):
    balance_repo = MagicMock()
    balance_repo.get_or_create.return_value = MagicMock(balance=balance)
    return balance_repo


def _debit_ready_repo(balance=100):
    balance_repo = MagicMock()
    balance_repo.find_by_user_id.return_value = MagicMock(balance=balance)
    return balance_repo


class TestCreditPublishes:
    def test_payload_carries_the_whole_movement(self, session, published):
        user_id = uuid4()
        reference_id = uuid4()

        _service(session, balance_repo=_credit_ready_repo(balance=10)).credit_tokens(
            user_id=user_id,
            amount=50,
            transaction_type=TokenTransactionType.PURCHASE,
            reference_id=reference_id,
        )

        assert len(published) == 1
        event_name, payload = published[0]
        assert event_name == EVENT_NAME
        assert payload == {
            "user_id": str(user_id),
            "delta": 50,
            "balance_after": 60,
            "transaction_type": TokenTransactionType.PURCHASE.value,
            "reference_id": str(reference_id),
        }

    def test_a_movement_without_a_reference_publishes_none_for_it(
        self, session, published
    ):
        _service(session, balance_repo=_credit_ready_repo()).credit_tokens(
            user_id=uuid4(),
            amount=5,
            transaction_type=TokenTransactionType.BONUS,
        )

        assert published[0][1]["reference_id"] is None


class TestDebitAndRefundPublish:
    def test_debit_publishes_a_negative_delta(self, session, published):
        _service(session, balance_repo=_debit_ready_repo()).debit_tokens(
            user_id=uuid4(),
            amount=30,
            transaction_type=TokenTransactionType.USAGE,
        )

        assert published[0][1]["delta"] == -30
        assert published[0][1]["balance_after"] == 70

    def test_refund_publishes_the_clamped_delta(self, session, published):
        _service(session, balance_repo=_debit_ready_repo(balance=30)).refund_tokens(
            user_id=uuid4(), amount=100
        )

        assert published[0][1]["delta"] == -30
        assert published[0][1]["transaction_type"] == TokenTransactionType.REFUND.value

    def test_complete_purchase_publishes_once(self, session, published):
        purchase_id = uuid4()
        purchase = MagicMock(
            id=purchase_id,
            user_id=uuid4(),
            token_amount=250,
            status=PurchaseStatus.PENDING,
        )
        purchase_repo = MagicMock()
        purchase_repo.find_by_id.return_value = purchase

        _service(
            session,
            balance_repo=_credit_ready_repo(balance=0),
            purchase_repo=purchase_repo,
        ).complete_purchase(purchase_id)

        assert len(published) == 1
        assert published[0][1]["delta"] == 250


class TestNeverPublishesAMovementThatDidNotHappen:
    def test_a_vetoed_movement_publishes_nothing(self, session, published):
        register_token_movement_hook(RaisingHook())

        with pytest.raises(RuntimeError, match="bookkeeping failed"):
            _service(session, balance_repo=_credit_ready_repo()).credit_tokens(
                user_id=uuid4(),
                amount=50,
                transaction_type=TokenTransactionType.PURCHASE,
            )

        assert published == []

    def test_a_failed_commit_publishes_nothing(self, session, published):
        session.commit.side_effect = RuntimeError("commit failed")

        with pytest.raises(RuntimeError, match="commit failed"):
            _service(session, balance_repo=_credit_ready_repo()).credit_tokens(
                user_id=uuid4(),
                amount=50,
                transaction_type=TokenTransactionType.PURCHASE,
            )

        assert published == []

    def test_a_rejected_amount_publishes_nothing(self, session, published):
        with pytest.raises(ValueError, match="positive"):
            _service(session, balance_repo=_credit_ready_repo()).credit_tokens(
                user_id=uuid4(),
                amount=0,
                transaction_type=TokenTransactionType.PURCHASE,
            )

        assert published == []

    def test_a_refund_with_nothing_to_refund_publishes_nothing(
        self, session, published
    ):
        balance_repo = MagicMock()
        balance_repo.find_by_user_id.return_value = None

        _service(session, balance_repo=balance_repo).refund_tokens(
            user_id=uuid4(), amount=50
        )

        assert published == []

    def test_a_composed_movement_defers_the_publish_to_its_caller(
        self, session, published
    ):
        """``commit=False`` means core has NOT made the movement durable.

        Publishing here would announce a movement the caller may still roll
        back — precisely what "after commit" exists to prevent. The hook still
        fires, so critical consumers are unaffected; this is the documented
        limit of the best-effort event.
        """
        _service(session, balance_repo=_credit_ready_repo()).credit_tokens(
            user_id=uuid4(),
            amount=50,
            transaction_type=TokenTransactionType.PURCHASE,
            commit=False,
        )

        assert published == []


class TestPublishIsBestEffort:
    def test_a_raising_subscriber_never_breaks_the_movement(self, session):
        def _bad_subscriber(event_name, data):
            raise RuntimeError("notifier down")

        event_bus.subscribe(EVENT_NAME, _bad_subscriber)
        try:
            balance = _service(
                session, balance_repo=_credit_ready_repo(balance=10)
            ).credit_tokens(
                user_id=uuid4(),
                amount=50,
                transaction_type=TokenTransactionType.PURCHASE,
            )
        finally:
            event_bus.unsubscribe(EVENT_NAME, _bad_subscriber)

        assert balance.balance == 60
        session.commit.assert_called_once()
        session.rollback.assert_not_called()

    def test_publishing_happens_after_the_commit(self, session):
        order = []
        session.commit.side_effect = lambda: order.append("commit")

        def _subscriber(event_name, data):
            order.append("publish")

        event_bus.subscribe(EVENT_NAME, _subscriber)
        try:
            _service(session, balance_repo=_credit_ready_repo()).credit_tokens(
                user_id=uuid4(),
                amount=50,
                transaction_type=TokenTransactionType.PURCHASE,
            )
        finally:
            event_bus.unsubscribe(EVENT_NAME, _subscriber)

        assert order == ["commit", "publish"]

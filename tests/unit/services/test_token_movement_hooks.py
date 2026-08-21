"""S138.0 Inc 1 — the core token-movement hook seam (domain-neutral).

``TokenService`` runs every registered hook INSIDE its own transaction, before
commit, so an external bookkeeper can mirror the balance exactly. A hook that
raises propagates — the whole token write rolls back with it.

These are unit tests: repositories and the session are ``MagicMock``. The
atomicity/rollback proof against a real database lives in
``tests/integration/test_token_service_atomicity.py``.
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.enums import PurchaseStatus, TokenTransactionType
from vbwd.services.token_balance_hooks import (
    ITokenMovementHook,
    TokenMovement,
    clear_token_movement_hooks,
    register_token_movement_hook,
    token_movement_hooks,
)
from vbwd.services.token_service import TokenService


class RecordingHook(ITokenMovementHook):
    """Test double that records every movement it is handed.

    Honours the base contract exactly (Liskov): it never swallows, never
    reorders, and returns ``None`` like a production hook.
    """

    def __init__(self) -> None:
        self.movements = []
        self.sessions = []

    def on_token_moved(self, movement: TokenMovement, session) -> None:
        self.movements.append(movement)
        self.sessions.append(session)


class RaisingHook(ITokenMovementHook):
    """Test double that vetoes every movement by raising."""

    def on_token_moved(self, movement: TokenMovement, session) -> None:
        raise RuntimeError("bookkeeping failed")


@pytest.fixture(autouse=True)
def _clean_hook_registry():
    clear_token_movement_hooks()
    yield
    clear_token_movement_hooks()


@pytest.fixture
def session():
    return MagicMock()


def _service(session, balance_repo=None, transaction_repo=None, purchase_repo=None):
    return TokenService(
        balance_repo=balance_repo or MagicMock(),
        transaction_repo=transaction_repo or MagicMock(),
        purchase_repo=purchase_repo or MagicMock(),
        session=session,
    )


class TestTokenMovementHookRegistry:
    """The registry is a plain core seam: register / read / clear."""

    def test_registry_is_empty_by_default(self):
        assert token_movement_hooks() == []

    def test_register_appends_in_order(self):
        first, second = RecordingHook(), RecordingHook()

        register_token_movement_hook(first)
        register_token_movement_hook(second)

        assert token_movement_hooks() == [first, second]

    def test_hooks_returns_a_copy(self):
        register_token_movement_hook(RecordingHook())

        token_movement_hooks().clear()

        assert len(token_movement_hooks()) == 1

    def test_clear_removes_every_hook(self):
        register_token_movement_hook(RecordingHook())

        clear_token_movement_hooks()

        assert token_movement_hooks() == []


class TestCreditFiresHook:
    """credit_tokens hands hooks a POSITIVE delta and the post-move balance."""

    def test_hook_receives_signed_delta_and_balance_after(self, session):
        hook = RecordingHook()
        register_token_movement_hook(hook)
        user_id = uuid4()
        reference_id = uuid4()
        balance_repo = MagicMock()
        balance_repo.get_or_create.return_value = MagicMock(balance=10)

        _service(session, balance_repo=balance_repo).credit_tokens(
            user_id=user_id,
            amount=50,
            transaction_type=TokenTransactionType.PURCHASE,
            reference_id=reference_id,
            description="Token bundle purchase",
        )

        assert len(hook.movements) == 1
        movement = hook.movements[0]
        assert movement.user_id == user_id
        assert movement.delta == 50
        assert movement.balance_after == 60
        assert movement.transaction_type == TokenTransactionType.PURCHASE
        assert movement.reference_id == reference_id
        assert movement.description == "Token bundle purchase"

    def test_hook_receives_the_live_session(self, session):
        hook = RecordingHook()
        register_token_movement_hook(hook)
        balance_repo = MagicMock()
        balance_repo.get_or_create.return_value = MagicMock(balance=0)

        _service(session, balance_repo=balance_repo).credit_tokens(
            user_id=uuid4(),
            amount=5,
            transaction_type=TokenTransactionType.BONUS,
        )

        assert hook.sessions == [session]

    def test_hooks_run_before_commit(self, session):
        """The hook must see the movement inside the still-open transaction."""
        commit_order = []
        session.commit.side_effect = lambda: commit_order.append("commit")
        hook = RecordingHook()
        hook.on_token_moved = lambda movement, s: commit_order.append("hook")
        register_token_movement_hook(hook)
        balance_repo = MagicMock()
        balance_repo.get_or_create.return_value = MagicMock(balance=0)

        _service(session, balance_repo=balance_repo).credit_tokens(
            user_id=uuid4(),
            amount=5,
            transaction_type=TokenTransactionType.BONUS,
        )

        assert commit_order == ["hook", "commit"]

    def test_every_registered_hook_fires(self, session):
        first, second = RecordingHook(), RecordingHook()
        register_token_movement_hook(first)
        register_token_movement_hook(second)
        balance_repo = MagicMock()
        balance_repo.get_or_create.return_value = MagicMock(balance=0)

        _service(session, balance_repo=balance_repo).credit_tokens(
            user_id=uuid4(),
            amount=7,
            transaction_type=TokenTransactionType.BONUS,
        )

        assert len(first.movements) == 1
        assert len(second.movements) == 1


class TestDebitFiresHook:
    """debit_tokens hands hooks a NEGATIVE delta (never the absolute amount)."""

    def test_hook_receives_negative_delta_and_balance_after(self, session):
        hook = RecordingHook()
        register_token_movement_hook(hook)
        user_id = uuid4()
        balance_repo = MagicMock()
        balance_repo.find_by_user_id.return_value = MagicMock(balance=100)

        _service(session, balance_repo=balance_repo).debit_tokens(
            user_id=user_id,
            amount=30,
            transaction_type=TokenTransactionType.USAGE,
            description="Metered usage",
        )

        movement = hook.movements[0]
        assert movement.user_id == user_id
        assert movement.delta == -30
        assert movement.balance_after == 70
        assert movement.transaction_type == TokenTransactionType.USAGE
        assert movement.reference_id is None
        assert movement.description == "Metered usage"

    def test_no_hook_fires_when_balance_insufficient(self, session):
        hook = RecordingHook()
        register_token_movement_hook(hook)
        balance_repo = MagicMock()
        balance_repo.find_by_user_id.return_value = MagicMock(balance=10)

        with pytest.raises(ValueError, match="Insufficient"):
            _service(session, balance_repo=balance_repo).debit_tokens(
                user_id=uuid4(),
                amount=50,
                transaction_type=TokenTransactionType.USAGE,
            )

        assert hook.movements == []
        session.commit.assert_not_called()


class TestRefundFiresHook:
    """refund_tokens bypasses debit_tokens — it must fire hooks in its own right."""

    def test_hook_receives_the_clamped_negative_delta(self, session):
        hook = RecordingHook()
        register_token_movement_hook(hook)
        user_id = uuid4()
        reference_id = uuid4()
        balance_repo = MagicMock()
        balance_repo.find_by_user_id.return_value = MagicMock(balance=30)

        actual_debit = _service(session, balance_repo=balance_repo).refund_tokens(
            user_id=user_id,
            amount=100,
            reference_id=reference_id,
            description="Refund",
        )

        assert actual_debit == 30
        movement = hook.movements[0]
        assert movement.delta == -30
        assert movement.balance_after == 0
        assert movement.transaction_type == TokenTransactionType.REFUND
        assert movement.reference_id == reference_id

    def test_no_hook_fires_when_there_is_nothing_to_refund(self, session):
        hook = RecordingHook()
        register_token_movement_hook(hook)
        balance_repo = MagicMock()
        balance_repo.find_by_user_id.return_value = None

        assert (
            _service(session, balance_repo=balance_repo).refund_tokens(
                user_id=uuid4(), amount=50
            )
            == 0
        )
        assert hook.movements == []


class TestCompletePurchaseFiresHook:
    """complete_purchase credits through credit_tokens, so it inherits the seam."""

    def test_fires_exactly_one_hook_via_credit_tokens(self, session):
        hook = RecordingHook()
        register_token_movement_hook(hook)
        purchase_id = uuid4()
        user_id = uuid4()
        purchase = MagicMock(
            id=purchase_id,
            user_id=user_id,
            token_amount=250,
            status=PurchaseStatus.PENDING,
        )
        purchase_repo = MagicMock()
        purchase_repo.find_by_id.return_value = purchase
        balance_repo = MagicMock()
        balance_repo.get_or_create.return_value = MagicMock(balance=0)

        _service(
            session, balance_repo=balance_repo, purchase_repo=purchase_repo
        ).complete_purchase(purchase_id)

        assert len(hook.movements) == 1
        movement = hook.movements[0]
        assert movement.delta == 250
        assert movement.balance_after == 250
        assert movement.transaction_type == TokenTransactionType.PURCHASE
        assert movement.reference_id == purchase_id


class TestRaisingHookRollsBack:
    """A hook raising propagates and takes the token write down with it."""

    def test_credit_rolls_back_and_never_commits(self, session):
        register_token_movement_hook(RaisingHook())
        balance_repo = MagicMock()
        balance_repo.get_or_create.return_value = MagicMock(balance=10)

        with pytest.raises(RuntimeError, match="bookkeeping failed"):
            _service(session, balance_repo=balance_repo).credit_tokens(
                user_id=uuid4(),
                amount=50,
                transaction_type=TokenTransactionType.PURCHASE,
            )

        session.commit.assert_not_called()
        session.rollback.assert_called_once()

    def test_debit_rolls_back_and_never_commits(self, session):
        register_token_movement_hook(RaisingHook())
        balance_repo = MagicMock()
        balance_repo.find_by_user_id.return_value = MagicMock(balance=100)

        with pytest.raises(RuntimeError, match="bookkeeping failed"):
            _service(session, balance_repo=balance_repo).debit_tokens(
                user_id=uuid4(),
                amount=30,
                transaction_type=TokenTransactionType.USAGE,
            )

        session.commit.assert_not_called()
        session.rollback.assert_called_once()

    def test_refund_rolls_back_and_never_commits(self, session):
        register_token_movement_hook(RaisingHook())
        balance_repo = MagicMock()
        balance_repo.find_by_user_id.return_value = MagicMock(balance=100)

        with pytest.raises(RuntimeError, match="bookkeeping failed"):
            _service(session, balance_repo=balance_repo).refund_tokens(
                user_id=uuid4(), amount=30
            )

        session.commit.assert_not_called()
        session.rollback.assert_called_once()


class TestZeroHooksIsTodaysBehaviour:
    """Regression guard for every existing caller: no hooks == no change."""

    def test_credit_still_returns_the_updated_balance_and_commits_once(self, session):
        balance = MagicMock(balance=10)
        balance_repo = MagicMock()
        balance_repo.get_or_create.return_value = balance

        result = _service(session, balance_repo=balance_repo).credit_tokens(
            user_id=uuid4(),
            amount=50,
            transaction_type=TokenTransactionType.PURCHASE,
        )

        assert result is balance
        assert balance.balance == 60
        session.commit.assert_called_once()
        session.rollback.assert_not_called()

    def test_debit_still_returns_the_updated_balance_and_commits_once(self, session):
        balance = MagicMock(balance=100)
        balance_repo = MagicMock()
        balance_repo.find_by_user_id.return_value = balance

        result = _service(session, balance_repo=balance_repo).debit_tokens(
            user_id=uuid4(),
            amount=40,
            transaction_type=TokenTransactionType.USAGE,
        )

        assert result is balance
        assert balance.balance == 60
        session.commit.assert_called_once()
        session.rollback.assert_not_called()

    def test_refund_still_clamps_and_returns_the_actual_debit(self, session):
        balance = MagicMock(balance=30)
        balance_repo = MagicMock()
        balance_repo.find_by_user_id.return_value = balance

        actual_debit = _service(session, balance_repo=balance_repo).refund_tokens(
            user_id=uuid4(), amount=100
        )

        assert actual_debit == 30
        assert balance.balance == 0
        session.commit.assert_called_once()

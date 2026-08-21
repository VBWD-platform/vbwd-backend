"""S138.0 Inc 2 — commit boundary, integer contract, and complete_purchase.

Three properties this increment adds to the Inc 1 unit of work:

1. ``commit=False`` lets a caller compose a movement into its own transaction:
   the movement is still flushed and the hooks still fire (so the caller's
   transaction sees it), but the commit belongs to the caller.
2. ``amount`` is an integer *contract*, not just a type hint. ``2.5`` used to
   pass the ``amount <= 0`` guard and let Postgres round it into the
   ``db.Integer`` column; ``True`` used to credit one token.
3. ``complete_purchase`` is ONE unit of work. It used to ``save()`` the
   ``COMPLETED`` status — which commits — *before* crediting, so a vetoed credit
   left a durably completed purchase with no tokens.

Unit tests: repositories and the session are ``MagicMock``. The live-DB proof
lives in ``tests/integration/test_token_service_atomicity.py``.
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.enums import PurchaseStatus, TokenTransactionType
from vbwd.models.user_token_balance import TokenTransaction
from vbwd.services.token_balance_hooks import (
    ITokenMovementHook,
    clear_token_movement_hooks,
    register_token_movement_hook,
)
from vbwd.services.token_service import TokenService


class RecordingHook(ITokenMovementHook):
    """Test double recording every movement (honours the base contract)."""

    def __init__(self) -> None:
        self.movements = []

    def on_token_moved(self, movement, session) -> None:
        self.movements.append(movement)


class RaisingHook(ITokenMovementHook):
    """Test double vetoing every movement by raising."""

    def on_token_moved(self, movement, session) -> None:
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


def _credit_ready_repo(balance=0):
    balance_repo = MagicMock()
    balance_repo.get_or_create.return_value = MagicMock(balance=balance)
    return balance_repo


def _debit_ready_repo(balance=100):
    balance_repo = MagicMock()
    balance_repo.find_by_user_id.return_value = MagicMock(balance=balance)
    return balance_repo


class TestCommitFalseComposesInTheCallersTransaction:
    """``commit=False``: flush + hooks, but the caller owns the commit."""

    def test_credit_flushes_and_fires_hooks_without_committing(self, session):
        hook = RecordingHook()
        register_token_movement_hook(hook)
        balance_repo = _credit_ready_repo(balance=10)

        _service(session, balance_repo=balance_repo).credit_tokens(
            user_id=uuid4(),
            amount=50,
            transaction_type=TokenTransactionType.PURCHASE,
            commit=False,
        )

        session.flush.assert_called_once()
        session.commit.assert_not_called()
        assert [movement.delta for movement in hook.movements] == [50]
        assert hook.movements[0].balance_after == 60

    def test_debit_flushes_and_fires_hooks_without_committing(self, session):
        hook = RecordingHook()
        register_token_movement_hook(hook)

        _service(session, balance_repo=_debit_ready_repo()).debit_tokens(
            user_id=uuid4(),
            amount=30,
            transaction_type=TokenTransactionType.USAGE,
            commit=False,
        )

        session.flush.assert_called_once()
        session.commit.assert_not_called()
        assert [movement.delta for movement in hook.movements] == [-30]

    def test_refund_flushes_and_fires_hooks_without_committing(self, session):
        hook = RecordingHook()
        register_token_movement_hook(hook)

        actual_debit = _service(
            session, balance_repo=_debit_ready_repo(balance=30)
        ).refund_tokens(user_id=uuid4(), amount=100, commit=False)

        assert actual_debit == 30
        session.flush.assert_called_once()
        session.commit.assert_not_called()
        assert [movement.delta for movement in hook.movements] == [-30]

    def test_the_balance_row_still_moves_so_the_caller_sees_it(self, session):
        balance = MagicMock(balance=10)
        balance_repo = MagicMock()
        balance_repo.get_or_create.return_value = balance

        result = _service(session, balance_repo=balance_repo).credit_tokens(
            user_id=uuid4(),
            amount=5,
            transaction_type=TokenTransactionType.BONUS,
            commit=False,
        )

        assert result is balance
        assert balance.balance == 15
        session.add.assert_any_call(balance)

    def test_committing_remains_the_default(self, session):
        _service(session, balance_repo=_credit_ready_repo()).credit_tokens(
            user_id=uuid4(),
            amount=5,
            transaction_type=TokenTransactionType.BONUS,
        )

        session.commit.assert_called_once()


class TestCommitFalseStillRollsBackOnFailure:
    """A vetoed movement must never stay pending in the caller's session.

    Without the rollback the flushed mutation would ride along on the caller's
    next ``commit()`` — persisting a movement its hook rejected.
    """

    def test_credit_rolls_back_when_a_hook_raises(self, session):
        register_token_movement_hook(RaisingHook())

        with pytest.raises(RuntimeError, match="bookkeeping failed"):
            _service(session, balance_repo=_credit_ready_repo()).credit_tokens(
                user_id=uuid4(),
                amount=50,
                transaction_type=TokenTransactionType.PURCHASE,
                commit=False,
            )

        session.rollback.assert_called_once()
        session.commit.assert_not_called()

    def test_debit_rolls_back_when_a_hook_raises(self, session):
        register_token_movement_hook(RaisingHook())

        with pytest.raises(RuntimeError, match="bookkeeping failed"):
            _service(session, balance_repo=_debit_ready_repo()).debit_tokens(
                user_id=uuid4(),
                amount=30,
                transaction_type=TokenTransactionType.USAGE,
                commit=False,
            )

        session.rollback.assert_called_once()


class TestIntegerContract:
    """``amount: int`` is enforced, not merely annotated.

    Postgres silently rounds a float into the ``db.Integer`` column, so a
    fractional amount used to move a *different* number of tokens than the
    caller asked for — invisibly.
    """

    @pytest.mark.parametrize("amount", [2.5, 0.5, 1.0001])
    def test_credit_rejects_a_fractional_amount(self, session, amount):
        with pytest.raises(TypeError, match="whole number"):
            _service(session, balance_repo=_credit_ready_repo()).credit_tokens(
                user_id=uuid4(),
                amount=amount,
                transaction_type=TokenTransactionType.PURCHASE,
            )

        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    @pytest.mark.parametrize("amount", [2.5, 0.5])
    def test_debit_rejects_a_fractional_amount(self, session, amount):
        with pytest.raises(TypeError, match="whole number"):
            _service(session, balance_repo=_debit_ready_repo()).debit_tokens(
                user_id=uuid4(),
                amount=amount,
                transaction_type=TokenTransactionType.USAGE,
            )

        session.commit.assert_not_called()

    def test_refund_rejects_a_fractional_amount(self, session):
        with pytest.raises(TypeError, match="whole number"):
            _service(session, balance_repo=_debit_ready_repo()).refund_tokens(
                user_id=uuid4(), amount=2.5
            )

        session.commit.assert_not_called()

    def test_a_whole_valued_float_is_still_rejected(self, session):
        """``2.0`` is a float: accepting it would make the contract advisory."""
        with pytest.raises(TypeError, match="whole number"):
            _service(session, balance_repo=_credit_ready_repo()).credit_tokens(
                user_id=uuid4(),
                amount=2.0,
                transaction_type=TokenTransactionType.PURCHASE,
            )

    def test_a_bool_is_rejected_even_though_python_calls_it_an_int(self, session):
        """``True`` passes ``isinstance(x, int)`` and used to credit 1 token."""
        with pytest.raises(TypeError, match="whole number"):
            _service(session, balance_repo=_credit_ready_repo()).credit_tokens(
                user_id=uuid4(),
                amount=True,
                transaction_type=TokenTransactionType.PURCHASE,
            )

        session.commit.assert_not_called()

    def test_a_string_is_rejected(self, session):
        with pytest.raises(TypeError, match="whole number"):
            _service(session, balance_repo=_credit_ready_repo()).credit_tokens(
                user_id=uuid4(),
                amount="50",
                transaction_type=TokenTransactionType.PURCHASE,
            )

    def test_the_smallest_valid_amount_is_one_token(self, session):
        """Boundary: 1 credits, 0 is still the existing non-positive reject."""
        _service(session, balance_repo=_credit_ready_repo()).credit_tokens(
            user_id=uuid4(),
            amount=1,
            transaction_type=TokenTransactionType.BONUS,
        )

        session.commit.assert_called_once()

    def test_zero_is_still_rejected_as_non_positive_not_as_a_type_error(self, session):
        with pytest.raises(ValueError, match="positive"):
            _service(session, balance_repo=_credit_ready_repo()).credit_tokens(
                user_id=uuid4(),
                amount=0,
                transaction_type=TokenTransactionType.PURCHASE,
            )

    def test_a_rejected_amount_never_touches_the_balance(self, session):
        balance = MagicMock(balance=10)
        balance_repo = MagicMock()
        balance_repo.get_or_create.return_value = balance

        with pytest.raises(TypeError):
            _service(session, balance_repo=balance_repo).credit_tokens(
                user_id=uuid4(),
                amount=2.5,
                transaction_type=TokenTransactionType.PURCHASE,
            )

        assert balance.balance == 10
        session.add.assert_not_called()


class TestCompletePurchaseIsOneUnitOfWork:
    """The purchase status and its credit commit together, or not at all."""

    def _pending_purchase(self, user_id, purchase_id, token_amount=250):
        return MagicMock(
            id=purchase_id,
            user_id=user_id,
            token_amount=token_amount,
            status=PurchaseStatus.PENDING,
        )

    def test_a_vetoed_credit_leaves_the_purchase_pending(self, session):
        register_token_movement_hook(RaisingHook())
        purchase_id = uuid4()
        purchase = self._pending_purchase(uuid4(), purchase_id)
        purchase_repo = MagicMock()
        purchase_repo.find_by_id.return_value = purchase
        purchase_repo.save.side_effect = AssertionError(
            "complete_purchase must not commit the status through the repository"
        )

        with pytest.raises(RuntimeError, match="bookkeeping failed"):
            _service(
                session,
                balance_repo=_credit_ready_repo(),
                purchase_repo=purchase_repo,
            ).complete_purchase(purchase_id)

        session.commit.assert_not_called()
        session.rollback.assert_called()

    def test_the_status_is_marked_on_the_session_not_committed_by_the_repo(
        self, session
    ):
        purchase_id = uuid4()
        purchase = self._pending_purchase(uuid4(), purchase_id)
        purchase_repo = MagicMock()
        purchase_repo.find_by_id.return_value = purchase

        _service(
            session, balance_repo=_credit_ready_repo(), purchase_repo=purchase_repo
        ).complete_purchase(purchase_id)

        purchase_repo.save.assert_not_called()
        session.add.assert_any_call(purchase)
        assert purchase.status == PurchaseStatus.COMPLETED
        assert purchase.tokens_credited is True
        assert purchase.completed_at is not None

    def test_the_status_and_the_credit_share_a_single_commit(self, session):
        purchase_id = uuid4()
        purchase = self._pending_purchase(uuid4(), purchase_id)
        purchase_repo = MagicMock()
        purchase_repo.find_by_id.return_value = purchase

        _service(
            session, balance_repo=_credit_ready_repo(), purchase_repo=purchase_repo
        ).complete_purchase(purchase_id)

        session.commit.assert_called_once()
        added = [call.args[0] for call in session.add.call_args_list]
        assert purchase in added
        assert any(isinstance(item, TokenTransaction) for item in added)

    def test_a_failing_credit_rolls_the_status_back(self, session):
        """A pre-flush failure (validation) must not leave the status pending."""
        purchase_id = uuid4()
        purchase = self._pending_purchase(uuid4(), purchase_id, token_amount=0)
        purchase_repo = MagicMock()
        purchase_repo.find_by_id.return_value = purchase

        with pytest.raises(ValueError, match="positive"):
            _service(
                session,
                balance_repo=_credit_ready_repo(),
                purchase_repo=purchase_repo,
            ).complete_purchase(purchase_id)

        session.commit.assert_not_called()
        session.rollback.assert_called_once()

    def test_a_non_pending_purchase_is_still_rejected_without_a_rollback(self, session):
        purchase_id = uuid4()
        purchase = self._pending_purchase(uuid4(), purchase_id)
        purchase.status = PurchaseStatus.COMPLETED
        purchase_repo = MagicMock()
        purchase_repo.find_by_id.return_value = purchase

        with pytest.raises(ValueError, match="not pending"):
            _service(session, purchase_repo=purchase_repo).complete_purchase(
                purchase_id
            )

        session.rollback.assert_not_called()

    def test_a_missing_purchase_is_still_rejected(self, session):
        purchase_repo = MagicMock()
        purchase_repo.find_by_id.return_value = None

        with pytest.raises(ValueError, match="not found"):
            _service(session, purchase_repo=purchase_repo).complete_purchase(uuid4())

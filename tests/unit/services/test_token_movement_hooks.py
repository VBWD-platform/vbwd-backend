"""S138.0 — the token-movement hook seam (registry contract + service wiring).

Two layers are pinned here without a database:

1. The module-level registry (``register`` / ``clear`` / list / ``run``) — the
   same propagate-don't-swallow shape as ``user_provisioning_guard_registry``.
2. ``TokenService`` firing the seam INSIDE its unit of work: every movement
   hands each hook the correct SIGNED ``delta`` and ``balance_after`` on a
   credit AND a debit, the hook runs on the live session BEFORE the commit, a
   raising hook rolls the movement back, and with zero hooks registered the path
   is byte-identical to before the seam existed.
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.enums import TokenTransactionType
from vbwd.services.token_balance_hooks import (
    ITokenMovementHook,
    TokenMovement,
    clear_token_movement_hooks,
    register_token_movement_hook,
    run_token_movement_hooks,
    token_movement_hooks,
)


@pytest.fixture(autouse=True)
def _clean_hook_registry():
    """Never let a hook leak between tests."""
    clear_token_movement_hooks()
    yield
    clear_token_movement_hooks()


class _RecordingHook(ITokenMovementHook):
    """Captures each movement it is handed (and the commit state at that moment)."""

    def __init__(self, session=None):
        self.movements: list[TokenMovement] = []
        self.sessions: list[object] = []
        self.commit_called_when_fired: list[bool] = []
        self._session = session

    def on_token_moved(self, movement: TokenMovement, session) -> None:
        self.movements.append(movement)
        self.sessions.append(session)
        if self._session is not None:
            self.commit_called_when_fired.append(bool(self._session.commit.called))


class _RaisingHook(ITokenMovementHook):
    """A bookkeeper whose posting fails; the movement must abort."""

    def on_token_moved(self, movement: TokenMovement, session) -> None:
        raise RuntimeError("bookkeeping failed")


def _build_service(session, *, balance_mock=None, existing_balance=None):
    """A ``TokenService`` wired to MagicMock repositories on ``session``."""
    from vbwd.services.token_service import TokenService

    balance_repo = MagicMock()
    if balance_mock is not None:
        balance_repo.get_or_create.return_value = balance_mock
        balance_repo.find_by_user_id.return_value = balance_mock
    return TokenService(
        balance_repo=balance_repo,
        transaction_repo=MagicMock(),
        purchase_repo=MagicMock(),
        session=session,
    )


class TestRegistryContract:
    """register / clear / list / run — the seam's own contract."""

    def test_register_adds_a_hook_in_registration_order(self):
        first, second = _RecordingHook(), _RecordingHook()
        register_token_movement_hook(first)
        register_token_movement_hook(second)
        assert token_movement_hooks() == [first, second]

    def test_clear_removes_all_hooks(self):
        register_token_movement_hook(_RecordingHook())
        clear_token_movement_hooks()
        assert token_movement_hooks() == []

    def test_list_returns_a_copy_that_cannot_mutate_the_registry(self):
        register_token_movement_hook(_RecordingHook())
        listed = token_movement_hooks()
        listed.clear()
        assert len(token_movement_hooks()) == 1

    def test_run_invokes_every_hook_with_the_movement_and_session(self):
        first, second = _RecordingHook(), _RecordingHook()
        register_token_movement_hook(first)
        register_token_movement_hook(second)
        session = MagicMock()
        movement = TokenMovement(
            user_id=uuid4(),
            delta=7,
            balance_after=7,
            transaction_type=TokenTransactionType.BONUS,
        )

        run_token_movement_hooks(movement, session)

        assert first.movements == [movement]
        assert second.movements == [movement]
        assert first.sessions == [session]

    def test_run_with_no_hooks_is_a_noop(self):
        # Must not raise — zero hooks is the default, byte-identical behaviour.
        run_token_movement_hooks(
            TokenMovement(
                user_id=uuid4(),
                delta=1,
                balance_after=1,
                transaction_type=TokenTransactionType.BONUS,
            ),
            MagicMock(),
        )

    def test_run_propagates_a_hook_exception(self):
        register_token_movement_hook(_RaisingHook())
        with pytest.raises(RuntimeError, match="bookkeeping failed"):
            run_token_movement_hooks(
                TokenMovement(
                    user_id=uuid4(),
                    delta=1,
                    balance_after=1,
                    transaction_type=TokenTransactionType.BONUS,
                ),
                MagicMock(),
            )


class TestTokenServiceFiresTheSeam:
    """TokenService hands the hook the right signed movement, before commit."""

    def test_credit_fires_hook_with_positive_delta_and_balance_after(self):
        recording = _RecordingHook()
        register_token_movement_hook(recording)
        session = MagicMock()
        balance_mock = MagicMock(balance=10)
        service = _build_service(session, balance_mock=balance_mock)

        user_id = uuid4()
        reference_id = uuid4()
        service.credit_tokens(
            user_id=user_id,
            amount=50,
            transaction_type=TokenTransactionType.PURCHASE,
            reference_id=reference_id,
        )

        assert len(recording.movements) == 1
        movement = recording.movements[0]
        assert movement.delta == 50
        assert movement.balance_after == 60
        assert movement.user_id == user_id
        assert movement.reference_id == reference_id
        assert movement.transaction_type == TokenTransactionType.PURCHASE

    def test_debit_fires_hook_with_negative_delta_and_balance_after(self):
        recording = _RecordingHook()
        register_token_movement_hook(recording)
        session = MagicMock()
        balance_mock = MagicMock(balance=100)
        service = _build_service(session, balance_mock=balance_mock)

        service.debit_tokens(
            user_id=uuid4(),
            amount=30,
            transaction_type=TokenTransactionType.USAGE,
        )

        assert len(recording.movements) == 1
        movement = recording.movements[0]
        assert movement.delta == -30
        assert movement.balance_after == 70

    def test_hook_runs_on_the_live_session_before_the_commit(self):
        session = MagicMock()
        recording = _RecordingHook(session=session)
        register_token_movement_hook(recording)
        balance_mock = MagicMock(balance=10)
        service = _build_service(session, balance_mock=balance_mock)

        service.credit_tokens(
            user_id=uuid4(),
            amount=5,
            transaction_type=TokenTransactionType.BONUS,
        )

        # Handed the service's own session, and the commit had NOT happened yet.
        assert recording.sessions == [session]
        assert recording.commit_called_when_fired == [False]
        session.commit.assert_called_once()

    def test_raising_hook_rolls_the_movement_back_and_propagates(self):
        register_token_movement_hook(_RaisingHook())
        session = MagicMock()
        balance_mock = MagicMock(balance=10)
        service = _build_service(session, balance_mock=balance_mock)

        with pytest.raises(RuntimeError, match="bookkeeping failed"):
            service.credit_tokens(
                user_id=uuid4(),
                amount=50,
                transaction_type=TokenTransactionType.PURCHASE,
            )

        session.rollback.assert_called_once()
        session.commit.assert_not_called()

    def test_zero_hooks_registered_is_unchanged_behaviour(self):
        assert token_movement_hooks() == []
        session = MagicMock()
        balance_mock = MagicMock(balance=10)
        service = _build_service(session, balance_mock=balance_mock)

        service.credit_tokens(
            user_id=uuid4(),
            amount=50,
            transaction_type=TokenTransactionType.PURCHASE,
        )

        assert balance_mock.balance == 60
        session.commit.assert_called_once()
        session.rollback.assert_not_called()

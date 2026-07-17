"""S138.0 Inc 1 — TokenService is ONE unit of work (live-DB integration).

Two properties, both previously untrue:

1. **The balance and its ``TokenTransaction`` commit together.** Today
   ``credit_tokens`` saves the balance through ``BaseRepository.save`` (which
   commits) and only *then* creates the transaction (another commit) — a failure
   between the two leaves a balance change with no ledger row.
2. **A registered hook raising rolls the whole token write back**, so an
   external bookkeeper can never drift from the core balance.

Mirrors ``test_admin_user_provisioning_guard``: ``create_app`` against the live
integration DB, real repositories, real session.
"""
from unittest.mock import patch
from uuid import uuid4

import pytest

from vbwd.models.enums import TokenTransactionType, UserRole, UserStatus
from vbwd.models.user import User
from vbwd.models.user_token_balance import TokenTransaction, UserTokenBalance
from vbwd.services.token_balance_hooks import (
    ITokenMovementHook,
    clear_token_movement_hooks,
    register_token_movement_hook,
)

INITIAL_BALANCE = 100


class RaisingHook(ITokenMovementHook):
    """A bookkeeper whose posting fails — the token write must roll back."""

    def on_token_moved(self, movement, session) -> None:
        raise RuntimeError("bookkeeping failed")


@pytest.fixture
def app():
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    return create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": get_database_url(),
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "RATELIMIT_ENABLED": False,
        }
    )


@pytest.fixture(autouse=True)
def _clean_hook_registry():
    clear_token_movement_hooks()
    yield
    clear_token_movement_hooks()


def _build_token_service(session):
    from vbwd.repositories.token_bundle_purchase_repository import (
        TokenBundlePurchaseRepository,
    )
    from vbwd.repositories.token_repository import (
        TokenBalanceRepository,
        TokenTransactionRepository,
    )
    from vbwd.services.token_service import TokenService

    return TokenService(
        balance_repo=TokenBalanceRepository(session),
        transaction_repo=TokenTransactionRepository(session),
        purchase_repo=TokenBundlePurchaseRepository(session),
        session=session,
    )


@pytest.fixture
def user_with_balance(app):
    """A committed user holding ``INITIAL_BALANCE`` tokens; removed afterwards."""
    from vbwd.extensions import db

    with app.app_context():
        user = User(
            id=uuid4(),
            email=f"token-atomicity-{uuid4().hex[:8]}@example.com",
            password_hash="x",
            status=UserStatus.ACTIVE,
            role=UserRole.USER,
        )
        db.session.add(user)
        db.session.add(UserTokenBalance(user_id=user.id, balance=INITIAL_BALANCE))
        db.session.commit()
        user_id = user.id
        try:
            yield user_id
        finally:
            db.session.rollback()
            db.session.query(TokenTransaction).filter(
                TokenTransaction.user_id == user_id
            ).delete()
            db.session.query(UserTokenBalance).filter(
                UserTokenBalance.user_id == user_id
            ).delete()
            existing_user = db.session.get(User, user_id)
            if existing_user is not None:
                db.session.delete(existing_user)
            db.session.commit()


def _persisted_state(user_id):
    """Re-read the balance and transaction count from the database."""
    from vbwd.extensions import db

    db.session.expire_all()
    balance = (
        db.session.query(UserTokenBalance)
        .filter(UserTokenBalance.user_id == user_id)
        .first()
    )
    transaction_count = (
        db.session.query(TokenTransaction)
        .filter(TokenTransaction.user_id == user_id)
        .count()
    )
    return (balance.balance if balance else None), transaction_count


class TestBalanceAndTransactionCommitAtomically:
    """The double-commit bug: a failure after the balance mutation must not stick."""

    def test_credit_leaves_the_balance_untouched_when_the_transaction_fails(
        self, app, user_with_balance
    ):
        from vbwd.extensions import db

        with app.app_context():
            service = _build_token_service(db.session)

            with patch(
                "vbwd.services.token_service.TokenTransaction",
                side_effect=RuntimeError("ledger row failed"),
            ):
                with pytest.raises(RuntimeError, match="ledger row failed"):
                    service.credit_tokens(
                        user_id=user_with_balance,
                        amount=50,
                        transaction_type=TokenTransactionType.PURCHASE,
                    )

            balance, transaction_count = _persisted_state(user_with_balance)
            assert balance == INITIAL_BALANCE
            assert transaction_count == 0

    def test_debit_leaves_the_balance_untouched_when_the_transaction_fails(
        self, app, user_with_balance
    ):
        from vbwd.extensions import db

        with app.app_context():
            service = _build_token_service(db.session)

            with patch(
                "vbwd.services.token_service.TokenTransaction",
                side_effect=RuntimeError("ledger row failed"),
            ):
                with pytest.raises(RuntimeError, match="ledger row failed"):
                    service.debit_tokens(
                        user_id=user_with_balance,
                        amount=40,
                        transaction_type=TokenTransactionType.USAGE,
                    )

            balance, transaction_count = _persisted_state(user_with_balance)
            assert balance == INITIAL_BALANCE
            assert transaction_count == 0


class TestRaisingHookRollsTheWriteBack:
    """A failed bookkeeper posting must undo the token movement entirely."""

    def test_credit_rolls_back_balance_and_transaction(self, app, user_with_balance):
        from vbwd.extensions import db

        register_token_movement_hook(RaisingHook())

        with app.app_context():
            service = _build_token_service(db.session)

            with pytest.raises(RuntimeError, match="bookkeeping failed"):
                service.credit_tokens(
                    user_id=user_with_balance,
                    amount=50,
                    transaction_type=TokenTransactionType.PURCHASE,
                )

            balance, transaction_count = _persisted_state(user_with_balance)
            assert balance == INITIAL_BALANCE
            assert transaction_count == 0

    def test_debit_rolls_back_balance_and_transaction(self, app, user_with_balance):
        from vbwd.extensions import db

        register_token_movement_hook(RaisingHook())

        with app.app_context():
            service = _build_token_service(db.session)

            with pytest.raises(RuntimeError, match="bookkeeping failed"):
                service.debit_tokens(
                    user_id=user_with_balance,
                    amount=40,
                    transaction_type=TokenTransactionType.USAGE,
                )

            balance, transaction_count = _persisted_state(user_with_balance)
            assert balance == INITIAL_BALANCE
            assert transaction_count == 0

    def test_refund_rolls_back_balance_and_transaction(self, app, user_with_balance):
        from vbwd.extensions import db

        register_token_movement_hook(RaisingHook())

        with app.app_context():
            service = _build_token_service(db.session)

            with pytest.raises(RuntimeError, match="bookkeeping failed"):
                service.refund_tokens(user_id=user_with_balance, amount=40)

            balance, transaction_count = _persisted_state(user_with_balance)
            assert balance == INITIAL_BALANCE
            assert transaction_count == 0


class TestSuccessfulMovementStillPersists:
    """Zero hooks (and a passing hook) == today's behaviour: the write commits."""

    def test_credit_commits_balance_and_transaction_together(
        self, app, user_with_balance
    ):
        from vbwd.extensions import db

        with app.app_context():
            service = _build_token_service(db.session)

            service.credit_tokens(
                user_id=user_with_balance,
                amount=50,
                transaction_type=TokenTransactionType.PURCHASE,
                description="Token bundle purchase",
            )

            balance, transaction_count = _persisted_state(user_with_balance)
            assert balance == INITIAL_BALANCE + 50
            assert transaction_count == 1

    def test_balance_equals_the_sum_of_its_transactions(self, app, user_with_balance):
        from vbwd.extensions import db

        observed_movements = []

        class RecordingHook(ITokenMovementHook):
            def on_token_moved(self, movement, session) -> None:
                observed_movements.append(movement)

        register_token_movement_hook(RecordingHook())

        with app.app_context():
            service = _build_token_service(db.session)

            service.credit_tokens(
                user_id=user_with_balance,
                amount=50,
                transaction_type=TokenTransactionType.PURCHASE,
            )
            service.debit_tokens(
                user_id=user_with_balance,
                amount=30,
                transaction_type=TokenTransactionType.USAGE,
            )

            balance, transaction_count = _persisted_state(user_with_balance)
            assert balance == INITIAL_BALANCE + 50 - 30
            assert transaction_count == 2
            assert [movement.delta for movement in observed_movements] == [50, -30]
            assert [movement.balance_after for movement in observed_movements] == [
                150,
                120,
            ]

    def test_credit_for_a_user_with_no_balance_row_creates_one(self, app):
        from vbwd.extensions import db

        with app.app_context():
            user = User(
                id=uuid4(),
                email=f"token-fresh-{uuid4().hex[:8]}@example.com",
                password_hash="x",
                status=UserStatus.ACTIVE,
                role=UserRole.USER,
            )
            db.session.add(user)
            db.session.commit()
            user_id = user.id

            try:
                service = _build_token_service(db.session)
                service.credit_tokens(
                    user_id=user_id,
                    amount=25,
                    transaction_type=TokenTransactionType.BONUS,
                )

                balance, transaction_count = _persisted_state(user_id)
                assert balance == 25
                assert transaction_count == 1
            finally:
                db.session.rollback()
                db.session.query(TokenTransaction).filter(
                    TokenTransaction.user_id == user_id
                ).delete()
                db.session.query(UserTokenBalance).filter(
                    UserTokenBalance.user_id == user_id
                ).delete()
                existing_user = db.session.get(User, user_id)
                if existing_user is not None:
                    db.session.delete(existing_user)
                db.session.commit()

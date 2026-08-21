"""S138.0 Inc 4 — the admin PUT keeps balance == Σ(TokenTransaction.amount).

``PUT /api/v1/admin/users/<id>`` did an absolute ``existing.balance = value``
with no ``TokenTransaction`` and no hook. The balance could therefore diverge
from the sum of its own transactions with no trace — which is why "reconcile by
replaying the transactions" was never a viable fallback for a mirror.

Now the set is a delta through ``TokenService``, so the invariant holds for the
first time and a token-movement hook observes the admin's adjustment like any
other movement.
"""
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

INITIAL_BALANCE = 200


class RecordingHook(ITokenMovementHook):
    """Records every movement core hands it."""

    def __init__(self) -> None:
        self.movements = []

    def on_token_moved(self, movement, session) -> None:
        self.movements.append(movement)


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


@pytest.fixture
def user_with_balance(app):
    from vbwd.extensions import db

    with app.app_context():
        user = User(
            id=uuid4(),
            email=f"admin-token-{uuid4().hex[:8]}@example.com",
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


def _admin_update(session, user_id, token_balance):
    """Run the exact service call the admin PUT route makes."""
    from vbwd.repositories.user_details_repository import UserDetailsRepository
    from vbwd.repositories.user_repository import UserRepository
    from vbwd.repositories.token_bundle_purchase_repository import (
        TokenBundlePurchaseRepository,
    )
    from vbwd.repositories.token_repository import (
        TokenBalanceRepository,
        TokenTransactionRepository,
    )
    from vbwd.services.token_service import TokenService
    from vbwd.services.user_service import UserService

    service = UserService(
        user_repository=UserRepository(session),
        user_details_repository=UserDetailsRepository(session),
        token_service=TokenService(
            balance_repo=TokenBalanceRepository(session),
            transaction_repo=TokenTransactionRepository(session),
            purchase_repo=TokenBundlePurchaseRepository(session),
            session=session,
        ),
    )
    return service.admin_update(str(user_id), {"token_balance": token_balance}, session)


def _persisted(user_id):
    from vbwd.extensions import db

    db.session.expire_all()
    balance_row = (
        db.session.query(UserTokenBalance)
        .filter(UserTokenBalance.user_id == user_id)
        .first()
    )
    transactions = (
        db.session.query(TokenTransaction)
        .filter(TokenTransaction.user_id == user_id)
        .all()
    )
    return balance_row, transactions


class TestAdminSetProducesTransactionsAndHoldsTheInvariant:
    def test_raising_the_balance_writes_an_adjustment_transaction(
        self, app, user_with_balance
    ):
        from vbwd.extensions import db

        with app.app_context():
            _admin_update(db.session, user_with_balance, 500)
            db.session.commit()

            balance_row, transactions = _persisted(user_with_balance)
            assert balance_row.balance == 500
            assert len(transactions) == 1
            assert transactions[0].amount == 300
            assert transactions[0].transaction_type == TokenTransactionType.ADJUSTMENT

    def test_lowering_the_balance_writes_a_negative_adjustment(
        self, app, user_with_balance
    ):
        from vbwd.extensions import db

        with app.app_context():
            _admin_update(db.session, user_with_balance, 50)
            db.session.commit()

            balance_row, transactions = _persisted(user_with_balance)
            assert balance_row.balance == 50
            assert [transaction.amount for transaction in transactions] == [-150]

    def test_the_balance_equals_the_sum_of_its_transactions(
        self, app, user_with_balance
    ):
        """The invariant the absolute set made impossible.

        The seeded balance is the user's opening position, so the sum of the
        movements must equal the net change from it.
        """
        from vbwd.extensions import db

        with app.app_context():
            for target in (500, 120, 900):
                _admin_update(db.session, user_with_balance, target)
                db.session.commit()

            balance_row, transactions = _persisted(user_with_balance)
            assert balance_row.balance == 900
            assert sum(transaction.amount for transaction in transactions) == (
                900 - INITIAL_BALANCE
            )

    def test_the_admin_set_fires_the_token_movement_hook(self, app, user_with_balance):
        from vbwd.extensions import db

        hook = RecordingHook()
        register_token_movement_hook(hook)

        with app.app_context():
            _admin_update(db.session, user_with_balance, 500)
            db.session.commit()

            assert len(hook.movements) == 1
            movement = hook.movements[0]
            assert movement.user_id == user_with_balance
            assert movement.delta == 300
            assert movement.balance_after == 500
            assert movement.transaction_type == TokenTransactionType.ADJUSTMENT

    def test_a_user_with_no_balance_row_is_credited_from_zero(self, app):
        from vbwd.extensions import db

        with app.app_context():
            user = User(
                id=uuid4(),
                email=f"admin-token-fresh-{uuid4().hex[:8]}@example.com",
                password_hash="x",
                status=UserStatus.ACTIVE,
                role=UserRole.USER,
            )
            db.session.add(user)
            db.session.commit()
            user_id = user.id

            try:
                _admin_update(db.session, user_id, 75)
                db.session.commit()

                balance_row, transactions = _persisted(user_id)
                assert balance_row.balance == 75
                assert [transaction.amount for transaction in transactions] == [75]
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

"""S138.0 — a counting hook observes every core token path (live DB).

The sprint's DoD: "**Every** ``UserTokenBalance`` mutation fires the hook —
proven by a test that registers a counting hook and exercises [every path]. Any
path that doesn't fire is a bug this sprint exists to kill."

This file exercises the CORE paths end to end against a real database:

* bundle capture (``activate_line_item`` on invoice payment) — was a direct write
* bundle refund (``reverse_line_item``)
* refund restore (``restore_line_item``) — was a direct write
* ``complete_purchase``
* the admin ``PUT /admin/users/<id>`` token set — wrote no transaction at all
* plain credit / debit / refund

The plugin paths (subscription plan tokens, provisioning, token_payment
spend/refund, withdraw, referral, chat/dataset usage, meinchat transfer) all move
tokens by calling ``TokenService``; that they cannot do otherwise is proven
structurally — and for every future path too — by
``tests/unit/test_token_balance_write_oracle.py``, which fails if any module
outside ``TokenService`` mutates a balance. Their own suites cover their own
behaviour; duplicating them here would only couple core's suite to the plugin
set that happens to be checked out.

Also asserts the invariant the admin absolute-set used to make impossible:
``balance == sum(TokenTransaction.amount)``.
"""
from uuid import uuid4

import pytest

from vbwd.events.line_item_registry import LineItemContext
from vbwd.handlers.core_line_item_handler import CoreLineItemHandler
from vbwd.models.enums import (
    LineItemType,
    PurchaseStatus,
    TokenTransactionType,
    UserRole,
    UserStatus,
)
from vbwd.models.token_bundle import TokenBundle
from vbwd.models.token_bundle_purchase import TokenBundlePurchase
from vbwd.models.user import User
from vbwd.models.user_token_balance import TokenTransaction, UserTokenBalance
from vbwd.services.token_balance_hooks import (
    ITokenMovementHook,
    clear_token_movement_hooks,
    register_token_movement_hook,
)

BUNDLE_TOKENS = 500
BUNDLE_PRICE = 9.99


class CountingHook(ITokenMovementHook):
    """Counts and records every movement core hands it."""

    def __init__(self) -> None:
        self.movements = []

    def on_token_moved(self, movement, session) -> None:
        self.movements.append(movement)

    @property
    def deltas(self):
        return [movement.delta for movement in self.movements]


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


@pytest.fixture
def hook():
    counting_hook = CountingHook()
    clear_token_movement_hooks()
    register_token_movement_hook(counting_hook)
    yield counting_hook
    clear_token_movement_hooks()


@pytest.fixture
def user_id(app):
    """A committed user with no balance row; everything of theirs is removed."""
    from vbwd.extensions import db

    with app.app_context():
        user = User(
            id=uuid4(),
            email=f"hook-coverage-{uuid4().hex[:8]}@example.com",
            password_hash="x",
            status=UserStatus.ACTIVE,
            role=UserRole.USER,
        )
        db.session.add(user)
        db.session.commit()
        created_id = user.id
        try:
            yield created_id
        finally:
            db.session.rollback()
            db.session.query(TokenTransaction).filter(
                TokenTransaction.user_id == created_id
            ).delete()
            db.session.query(TokenBundlePurchase).filter(
                TokenBundlePurchase.user_id == created_id
            ).delete()
            db.session.query(UserTokenBalance).filter(
                UserTokenBalance.user_id == created_id
            ).delete()
            existing_user = db.session.get(User, created_id)
            if existing_user is not None:
                db.session.delete(existing_user)
            db.session.commit()


def _token_service(session):
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


def _make_purchase(session, user_id, status):
    bundle = TokenBundle(
        id=uuid4(),
        name=f"Hook coverage bundle {uuid4().hex[:8]}",
        token_amount=BUNDLE_TOKENS,
        price=BUNDLE_PRICE,
    )
    purchase = TokenBundlePurchase(
        id=uuid4(),
        user_id=user_id,
        bundle_id=bundle.id,
        status=status,
        tokens_credited=status is PurchaseStatus.COMPLETED,
        token_amount=BUNDLE_TOKENS,
        price=BUNDLE_PRICE,
    )
    session.add(bundle)
    session.add(purchase)
    session.commit()
    return purchase


def _line_item_context(app, user_id):
    class _FakeLineItem:
        item_type = LineItemType.TOKEN_BUNDLE

        def __init__(self, item_id):
            self.item_id = item_id

    class _FakeInvoice:
        def __init__(self, invoice_user_id):
            self.id = uuid4()
            self.user_id = invoice_user_id

    container = app.container
    return _FakeLineItem, LineItemContext(
        invoice=_FakeInvoice(user_id), user_id=user_id, container=container
    )


def _balance_and_transactions(user_id):
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
    return (balance_row.balance if balance_row else 0), transactions


def _assert_balance_equals_sum_of_transactions(user_id):
    balance, transactions = _balance_and_transactions(user_id)
    assert balance == sum(transaction.amount for transaction in transactions)
    return balance


class TestCoreServicePathsFireTheHook:
    def test_credit_debit_and_refund_each_fire_once(self, app, user_id, hook):
        from vbwd.extensions import db

        with app.app_context():
            service = _token_service(db.session)
            service.credit_tokens(
                user_id=user_id, amount=100, transaction_type=TokenTransactionType.BONUS
            )
            service.debit_tokens(
                user_id=user_id, amount=40, transaction_type=TokenTransactionType.USAGE
            )
            service.refund_tokens(user_id=user_id, amount=10)

            assert hook.deltas == [100, -40, -10]
            assert _assert_balance_equals_sum_of_transactions(user_id) == 50

    def test_complete_purchase_fires_the_hook(self, app, user_id, hook):
        from vbwd.extensions import db

        with app.app_context():
            purchase = _make_purchase(db.session, user_id, PurchaseStatus.PENDING)

            _token_service(db.session).complete_purchase(purchase.id)

            assert hook.deltas == [BUNDLE_TOKENS]
            assert hook.movements[0].transaction_type == TokenTransactionType.PURCHASE
            assert _assert_balance_equals_sum_of_transactions(user_id) == BUNDLE_TOKENS


class TestInvoiceLineItemPathsFireTheHook:
    """The three bundle paths on the invoice lifecycle.

    Capture and restore were direct writes before S138.0 Inc 3 — a hook saw
    neither.
    """

    def test_bundle_capture_fires_the_hook(self, app, user_id, hook):
        from vbwd.extensions import db

        with app.app_context():
            purchase = _make_purchase(db.session, user_id, PurchaseStatus.PENDING)
            line_item_class, context = _line_item_context(app, user_id)

            result = CoreLineItemHandler(app.container).activate_line_item(
                line_item_class(purchase.id), context
            )

            assert result.success is True
            assert hook.deltas == [BUNDLE_TOKENS]
            assert hook.movements[0].reference_id == purchase.id
            assert _assert_balance_equals_sum_of_transactions(user_id) == BUNDLE_TOKENS

    def test_bundle_refund_fires_the_hook(self, app, user_id, hook):
        from vbwd.extensions import db

        with app.app_context():
            service = _token_service(db.session)
            service.credit_tokens(
                user_id=user_id,
                amount=BUNDLE_TOKENS,
                transaction_type=TokenTransactionType.PURCHASE,
            )
            purchase = _make_purchase(db.session, user_id, PurchaseStatus.COMPLETED)
            line_item_class, context = _line_item_context(app, user_id)

            result = CoreLineItemHandler(app.container).reverse_line_item(
                line_item_class(purchase.id), context
            )

            assert result.success is True
            assert hook.deltas == [BUNDLE_TOKENS, -BUNDLE_TOKENS]
            assert hook.movements[1].transaction_type == TokenTransactionType.REFUND
            assert _assert_balance_equals_sum_of_transactions(user_id) == 0

    def test_refund_restore_fires_the_hook(self, app, user_id, hook):
        from vbwd.extensions import db

        with app.app_context():
            purchase = _make_purchase(db.session, user_id, PurchaseStatus.REFUNDED)
            line_item_class, context = _line_item_context(app, user_id)

            result = CoreLineItemHandler(app.container).restore_line_item(
                line_item_class(purchase.id), context
            )

            assert result.success is True
            assert hook.deltas == [BUNDLE_TOKENS]
            assert _assert_balance_equals_sum_of_transactions(user_id) == BUNDLE_TOKENS


class TestAdminUpdatePathFiresTheHook:
    """The killer path: an absolute set with no transaction and no event."""

    def test_the_admin_token_set_fires_the_hook(self, app, user_id, hook):
        from vbwd.extensions import db
        from vbwd.repositories.user_details_repository import UserDetailsRepository
        from vbwd.repositories.user_repository import UserRepository
        from vbwd.services.user_service import UserService

        with app.app_context():
            service = UserService(
                user_repository=UserRepository(db.session),
                user_details_repository=UserDetailsRepository(db.session),
                token_service=_token_service(db.session),
            )

            service.admin_update(str(user_id), {"token_balance": 750}, db.session)
            db.session.commit()

            assert hook.deltas == [750]
            assert hook.movements[0].transaction_type == TokenTransactionType.ADJUSTMENT
            assert _assert_balance_equals_sum_of_transactions(user_id) == 750


class TestTheInvariantSurvivesAMixOfPaths:
    def test_balance_equals_the_sum_of_transactions_after_every_path(
        self, app, user_id, hook
    ):
        from vbwd.extensions import db
        from vbwd.repositories.user_details_repository import UserDetailsRepository
        from vbwd.repositories.user_repository import UserRepository
        from vbwd.services.user_service import UserService

        with app.app_context():
            service = _token_service(db.session)
            purchase = _make_purchase(db.session, user_id, PurchaseStatus.PENDING)
            line_item_class, context = _line_item_context(app, user_id)

            CoreLineItemHandler(app.container).activate_line_item(
                line_item_class(purchase.id), context
            )
            service.debit_tokens(
                user_id=user_id, amount=120, transaction_type=TokenTransactionType.USAGE
            )
            UserService(
                user_repository=UserRepository(db.session),
                user_details_repository=UserDetailsRepository(db.session),
                token_service=service,
            ).admin_update(str(user_id), {"token_balance": 1000}, db.session)
            db.session.commit()
            service.refund_tokens(user_id=user_id, amount=250)

            assert len(hook.movements) == 4
            assert hook.deltas == [BUNDLE_TOKENS, -120, 620, -250]
            assert _assert_balance_equals_sum_of_transactions(user_id) == 750

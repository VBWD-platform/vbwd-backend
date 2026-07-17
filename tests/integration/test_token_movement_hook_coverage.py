"""S138.0 DoD — EVERY core token path fires the movement hook (live-DB).

The seam is worthless unless it is universal: a single registered
:class:`ITokenMovementHook` must observe every way core moves tokens, and after
each one the invariant ``balance == sum(TokenTransaction.amount)`` must hold. Any
path that mutates the balance without firing the hook is a hole S138.0 exists to
close.

Exercised here (the CORE paths — plugin paths are covered by each plugin's own
suite):

* ``TokenService.credit_tokens`` / ``debit_tokens`` / ``refund_tokens``
* ``TokenService.complete_purchase`` (bundle purchase → credit as one unit)
* ``CoreLineItemHandler`` bundle capture → refund → restore lifecycle
* the admin ``PUT /api/v1/admin/users/<id>`` token-balance adjustment

Mirrors ``test_token_service_atomicity`` / ``test_admin_user_provisioning_guard``:
``create_app`` against the live integration DB, the wired DI container, and the
Flask ``test_client`` with a monkeypatched admin auth for the route path.
"""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

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


class CountingHook(ITokenMovementHook):
    """Records every movement it observes, in order."""

    def __init__(self):
        self.movements = []

    def on_token_moved(self, movement, session) -> None:
        self.movements.append(movement)

    @property
    def call_count(self) -> int:
        return len(self.movements)


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


@contextmanager
def _user(app, *, initial_balance=None):
    """A committed user, optionally with a starting balance row; removed after."""
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
        if initial_balance is not None:
            # Seed the balance the way production reaches it — through a matching
            # transaction — so ``balance == sum(transactions)`` holds from the
            # start and every later movement must preserve it.
            db.session.add(UserTokenBalance(user_id=user.id, balance=initial_balance))
            db.session.add(
                TokenTransaction(
                    id=uuid4(),
                    user_id=user.id,
                    amount=initial_balance,
                    transaction_type=TokenTransactionType.ADJUSTMENT,
                    description="test starting balance",
                )
            )
        db.session.commit()
        user_id = user.id
        try:
            yield user_id
        finally:
            _cleanup_user(db, user_id)


def _cleanup_user(db, user_id):
    db.session.rollback()
    db.session.query(TokenTransaction).filter(
        TokenTransaction.user_id == user_id
    ).delete()
    db.session.query(UserTokenBalance).filter(
        UserTokenBalance.user_id == user_id
    ).delete()
    purchases = (
        db.session.query(TokenBundlePurchase)
        .filter(TokenBundlePurchase.user_id == user_id)
        .all()
    )
    bundle_ids = {purchase.bundle_id for purchase in purchases}
    db.session.query(TokenBundlePurchase).filter(
        TokenBundlePurchase.user_id == user_id
    ).delete()
    for bundle_id in bundle_ids:
        bundle = db.session.get(TokenBundle, bundle_id)
        if bundle is not None:
            db.session.delete(bundle)
    existing_user = db.session.get(User, user_id)
    if existing_user is not None:
        db.session.delete(existing_user)
    db.session.commit()


def _make_pending_purchase(db, user_id, token_amount):
    """A PENDING bundle purchase (with its bundle) for the line-item paths."""
    bundle = TokenBundle(
        id=uuid4(),
        name=f"bundle-{uuid4().hex[:8]}",
        token_amount=token_amount,
        price=10.0,
        is_active=True,
    )
    db.session.add(bundle)
    purchase = TokenBundlePurchase(
        id=uuid4(),
        user_id=user_id,
        bundle_id=bundle.id,
        status=PurchaseStatus.PENDING,
        token_amount=token_amount,
        price=10.0,
    )
    db.session.add(purchase)
    db.session.commit()
    return purchase.id


def _current_balance_and_ledger_sum(db, user_id):
    """The persisted balance and the sum of the user's ``TokenTransaction`` rows."""
    db.session.expire_all()
    balance_row = (
        db.session.query(UserTokenBalance)
        .filter(UserTokenBalance.user_id == user_id)
        .first()
    )
    ledger_sum = (
        db.session.query(TokenTransaction)
        .with_entities(TokenTransaction.amount)
        .filter(TokenTransaction.user_id == user_id)
        .all()
    )
    balance = balance_row.balance if balance_row else None
    return balance, sum(amount for (amount,) in ledger_sum)


def _assert_invariant_and_last_movement(db, user_id, hook):
    """balance == Σ transactions, and the last movement mirrors the balance."""
    balance, ledger_sum = _current_balance_and_ledger_sum(db, user_id)
    assert balance == ledger_sum, "balance drifted from the sum of its transactions"
    assert hook.movements, "the hook never fired for this path"
    assert hook.movements[-1].balance_after == balance


def _line_item(purchase_id):
    return SimpleNamespace(item_type=LineItemType.TOKEN_BUNDLE, item_id=purchase_id)


class TestDirectServicePathsFireTheHook:
    def test_credit_debit_and_refund_each_fire_the_hook(self, app):
        from vbwd.extensions import db

        with _user(app, initial_balance=100) as user_id:
            with app.app_context():
                hook = CountingHook()
                register_token_movement_hook(hook)
                service = app.container.token_service()

                service.credit_tokens(
                    user_id=user_id,
                    amount=50,
                    transaction_type=TokenTransactionType.BONUS,
                )
                assert hook.call_count == 1
                assert hook.movements[-1].delta == 50
                _assert_invariant_and_last_movement(db, user_id, hook)

                service.debit_tokens(
                    user_id=user_id,
                    amount=30,
                    transaction_type=TokenTransactionType.USAGE,
                )
                assert hook.call_count == 2
                assert hook.movements[-1].delta == -30
                _assert_invariant_and_last_movement(db, user_id, hook)

                service.refund_tokens(user_id=user_id, amount=20)
                assert hook.call_count == 3
                assert hook.movements[-1].delta == -20
                _assert_invariant_and_last_movement(db, user_id, hook)


class TestCompletePurchaseFiresTheHook:
    def test_complete_purchase_credits_and_fires_the_hook(self, app):
        from vbwd.extensions import db

        with _user(app) as user_id:
            with app.app_context():
                purchase_id = _make_pending_purchase(db, user_id, token_amount=75)
                hook = CountingHook()
                register_token_movement_hook(hook)

                app.container.token_service().complete_purchase(purchase_id)

                assert hook.call_count == 1
                assert hook.movements[-1].delta == 75
                _assert_invariant_and_last_movement(db, user_id, hook)


class TestBundleLineItemLifecycleFiresTheHook:
    def test_capture_refund_and_restore_each_fire_the_hook(self, app):
        from vbwd.extensions import db
        from vbwd.events.line_item_registry import LineItemContext
        from vbwd.handlers.core_line_item_handler import CoreLineItemHandler

        with _user(app) as user_id:
            with app.app_context():
                purchase_id = _make_pending_purchase(db, user_id, token_amount=40)
                hook = CountingHook()
                register_token_movement_hook(hook)

                handler = CoreLineItemHandler(app.container)
                context = LineItemContext(
                    invoice=None, user_id=user_id, container=app.container
                )
                line_item = _line_item(purchase_id)

                # Capture — credits the bundle's tokens.
                handler.activate_line_item(line_item, context)
                assert hook.call_count == 1
                assert hook.movements[-1].delta == 40
                _assert_invariant_and_last_movement(db, user_id, hook)

                # Refund — debits them back.
                handler.reverse_line_item(line_item, context)
                assert hook.call_count == 2
                assert hook.movements[-1].delta == -40
                _assert_invariant_and_last_movement(db, user_id, hook)

                # Restore (refund reversal) — credits them again.
                handler.restore_line_item(line_item, context)
                assert hook.call_count == 3
                assert hook.movements[-1].delta == 40
                _assert_invariant_and_last_movement(db, user_id, hook)


class TestAdminBalanceAdjustmentFiresTheHook:
    """The route that used to absolute-set the balance with no transaction."""

    def _auth_as(self, monkeypatch, admin):
        from unittest.mock import MagicMock

        import vbwd.middleware.auth as auth_mod

        repo = MagicMock()
        repo.find_by_id.return_value = admin
        svc = MagicMock()
        svc.verify_token.return_value = str(admin.id)
        monkeypatch.setattr(auth_mod, "UserRepository", lambda *a, **k: repo)
        monkeypatch.setattr(auth_mod, "AuthService", lambda *a, **k: svc)
        monkeypatch.setattr(type(admin), "is_admin", property(lambda self: True))
        monkeypatch.setattr(
            type(admin),
            "has_permission",
            lambda self, perm: perm == "users.manage",
        )

    def test_admin_put_writes_a_transaction_and_fires_the_hook(self, app, monkeypatch):
        from vbwd.extensions import db

        with _user(app, initial_balance=40) as user_id:
            with app.app_context():
                admin = User(
                    id=uuid4(),
                    email=f"hook-admin-{uuid4().hex[:8]}@example.com",
                    password_hash="x",
                    status=UserStatus.ACTIVE,
                    role=UserRole.ADMIN,
                )
                db.session.add(admin)
                db.session.commit()
                admin_id = admin.id

            hook = CountingHook()
            register_token_movement_hook(hook)
            self._auth_as(monkeypatch, admin)

            try:
                client = app.test_client()
                response = client.put(
                    f"/api/v1/admin/users/{user_id}",
                    json={"token_balance": 100},
                    headers={"Authorization": "Bearer valid"},
                )
                assert response.status_code == 200, response.get_data(as_text=True)

                with app.app_context():
                    assert hook.call_count == 1
                    assert hook.movements[-1].delta == 60
                    assert (
                        hook.movements[-1].transaction_type
                        == TokenTransactionType.ADJUSTMENT
                    )
                    _assert_invariant_and_last_movement(db, user_id, hook)
                    balance, _ = _current_balance_and_ledger_sum(db, user_id)
                    assert balance == 100
            finally:
                with app.app_context():
                    obj = db.session.get(User, admin_id)
                    if obj is not None:
                        db.session.delete(obj)
                        db.session.commit()

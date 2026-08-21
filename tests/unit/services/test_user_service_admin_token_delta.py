"""S138.0 Inc 4 — the admin token set is a delta through TokenService.

``PUT /api/v1/admin/users/<id>`` with ``{"token_balance": 500}`` used to do
``existing.balance = 500``: an ABSOLUTE set, writing no ``TokenTransaction`` and
firing nothing. That defeated even a fallback "reconcile by replaying the
transactions" strategy — the balance could diverge from the sum of its own
transactions with no trace.

It is now a delta routed through ``TokenService`` with
``TokenTransactionType.ADJUSTMENT`` and ``commit=False`` (so it composes with
the rest of ``admin_update``). The API's absolute-set semantics are unchanged
from the caller's view: asking for 500 still results in 500.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vbwd.models.enums import TokenTransactionType, UserRole, UserStatus
from vbwd.services.user_service import AdminUserUpdateError, UserService


@pytest.fixture
def user_stub():
    user = MagicMock()
    user.id = "user-1"
    user.status = UserStatus.ACTIVE
    user.role = UserRole.USER
    user.details = SimpleNamespace(
        first_name=None, last_name=None, phone=None, address_line_1=None
    )
    return user


@pytest.fixture
def user_repo(user_stub):
    repo = MagicMock()
    repo.find_by_id.return_value = user_stub
    repo.save.side_effect = lambda saved_user: saved_user
    return repo


@pytest.fixture
def token_service():
    service = MagicMock()
    service.get_balance.return_value = 0
    return service


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def service(user_repo, token_service):
    return UserService(
        user_repository=user_repo,
        user_details_repository=MagicMock(),
        token_service=token_service,
    )


class TestAdminSetBecomesADelta:
    def test_raising_the_balance_credits_the_difference(
        self, service, session, token_service, user_stub
    ):
        token_service.get_balance.return_value = 200

        service.admin_update("user-1", {"token_balance": 500}, session)

        token_service.credit_tokens.assert_called_once()
        call = token_service.credit_tokens.call_args.kwargs
        assert call["user_id"] == user_stub.id
        assert call["amount"] == 300
        assert call["transaction_type"] == TokenTransactionType.ADJUSTMENT
        assert call["commit"] is False
        token_service.debit_tokens.assert_not_called()

    def test_lowering_the_balance_debits_the_difference(
        self, service, session, token_service
    ):
        token_service.get_balance.return_value = 500

        service.admin_update("user-1", {"token_balance": 120}, session)

        token_service.debit_tokens.assert_called_once()
        call = token_service.debit_tokens.call_args.kwargs
        assert call["amount"] == 380
        assert call["transaction_type"] == TokenTransactionType.ADJUSTMENT
        assert call["commit"] is False
        token_service.credit_tokens.assert_not_called()

    def test_setting_the_balance_it_already_has_moves_nothing(
        self, service, session, token_service
    ):
        token_service.get_balance.return_value = 500

        service.admin_update("user-1", {"token_balance": 500}, session)

        token_service.credit_tokens.assert_not_called()
        token_service.debit_tokens.assert_not_called()

    def test_a_user_with_no_balance_row_is_credited_the_whole_amount(
        self, service, session, token_service
    ):
        token_service.get_balance.return_value = 0

        service.admin_update("user-1", {"token_balance": 500}, session)

        assert token_service.credit_tokens.call_args.kwargs["amount"] == 500

    def test_zero_for_a_user_with_no_balance_moves_nothing(
        self, service, session, token_service
    ):
        token_service.get_balance.return_value = 0

        service.admin_update("user-1", {"token_balance": 0}, session)

        token_service.credit_tokens.assert_not_called()
        token_service.debit_tokens.assert_not_called()

    def test_the_balance_row_is_never_written_directly(
        self, service, session, token_service
    ):
        token_service.get_balance.return_value = 10

        service.admin_update("user-1", {"token_balance": 99}, session)

        session.add.assert_not_called()

    def test_an_omitted_token_balance_touches_nothing(
        self, service, session, token_service
    ):
        service.admin_update("user-1", {"status": "active"}, session)

        token_service.get_balance.assert_not_called()
        token_service.credit_tokens.assert_not_called()
        token_service.debit_tokens.assert_not_called()


class TestExistingValidationPreserved:
    def test_a_negative_balance_is_still_rejected_before_any_movement(
        self, service, session, token_service
    ):
        with pytest.raises(AdminUserUpdateError, match="cannot be negative"):
            service.admin_update("user-1", {"token_balance": -5}, session)

        token_service.credit_tokens.assert_not_called()
        token_service.debit_tokens.assert_not_called()

    def test_a_non_numeric_balance_is_still_rejected(self, service, session):
        with pytest.raises(AdminUserUpdateError, match="Invalid token balance"):
            service.admin_update("user-1", {"token_balance": "abc"}, session)

    def test_a_numeric_string_is_still_coerced(self, service, session, token_service):
        token_service.get_balance.return_value = 0

        service.admin_update("user-1", {"token_balance": "500"}, session)

        assert token_service.credit_tokens.call_args.kwargs["amount"] == 500

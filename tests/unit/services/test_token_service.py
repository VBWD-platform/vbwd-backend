"""Tests for TokenService.

Since S138.0 every movement is one unit of work on the service's session
(``add`` + ``flush`` + a single ``commit``) rather than two repository saves
that each committed, so these assert against the session. The behaviour they
pin — clamping, validation, the signed transaction amount — is unchanged.
"""
from unittest.mock import MagicMock
from uuid import uuid4

from vbwd.models.enums import TokenTransactionType
from vbwd.models.user_token_balance import TokenTransaction


def _added_transaction(session):
    """The single TokenTransaction the service added to the session."""
    added = [call.args[0] for call in session.add.call_args_list]
    transactions = [item for item in added if isinstance(item, TokenTransaction)]
    assert len(transactions) == 1
    return transactions[0]


class TestTokenServiceRefundTokens:
    """Tests for TokenService.refund_tokens()."""

    def test_refund_tokens_debits_balance(self):
        """refund_tokens debits the correct amount from balance."""
        from vbwd.services.token_service import TokenService

        user_id = uuid4()
        session = MagicMock()
        balance_mock = MagicMock(balance=100)
        balance_repo = MagicMock()
        balance_repo.find_by_user_id.return_value = balance_mock
        transaction_repo = MagicMock()
        purchase_repo = MagicMock()

        service = TokenService(
            balance_repo=balance_repo,
            transaction_repo=transaction_repo,
            purchase_repo=purchase_repo,
            session=session,
        )

        actual = service.refund_tokens(
            user_id=user_id,
            amount=50,
            reference_id=uuid4(),
            description="Refund: 50 tokens",
        )

        assert actual == 50
        assert balance_mock.balance == 50
        session.add.assert_any_call(balance_mock)
        session.commit.assert_called_once()
        transaction = _added_transaction(session)
        assert transaction.amount == -50
        assert transaction.transaction_type == TokenTransactionType.REFUND

    def test_refund_tokens_clamps_to_zero(self):
        """refund_tokens clamps debit to available balance when insufficient."""
        from vbwd.services.token_service import TokenService

        user_id = uuid4()
        session = MagicMock()
        balance_mock = MagicMock(balance=30)
        balance_repo = MagicMock()
        balance_repo.find_by_user_id.return_value = balance_mock
        transaction_repo = MagicMock()
        purchase_repo = MagicMock()

        service = TokenService(
            balance_repo=balance_repo,
            transaction_repo=transaction_repo,
            purchase_repo=purchase_repo,
            session=session,
        )

        actual = service.refund_tokens(user_id=user_id, amount=100)

        assert actual == 30
        assert balance_mock.balance == 0
        session.add.assert_any_call(balance_mock)
        assert _added_transaction(session).amount == -30

    def test_refund_tokens_returns_zero_when_no_balance(self):
        """refund_tokens returns 0 when user has no balance record."""
        from vbwd.services.token_service import TokenService

        session = MagicMock()
        balance_repo = MagicMock()
        balance_repo.find_by_user_id.return_value = None
        transaction_repo = MagicMock()
        purchase_repo = MagicMock()

        service = TokenService(
            balance_repo=balance_repo,
            transaction_repo=transaction_repo,
            purchase_repo=purchase_repo,
            session=session,
        )

        actual = service.refund_tokens(user_id=uuid4(), amount=50)

        assert actual == 0
        session.add.assert_not_called()
        session.commit.assert_not_called()


class TestTokenServiceCreditTokens:
    """Tests for TokenService.credit_tokens()."""

    def test_credit_tokens_increases_balance(self):
        """credit_tokens increases user balance."""
        from vbwd.services.token_service import TokenService

        user_id = uuid4()
        session = MagicMock()
        balance_mock = MagicMock(balance=10)
        balance_repo = MagicMock()
        balance_repo.get_or_create.return_value = balance_mock
        transaction_repo = MagicMock()
        purchase_repo = MagicMock()

        service = TokenService(
            balance_repo=balance_repo,
            transaction_repo=transaction_repo,
            purchase_repo=purchase_repo,
            session=session,
        )

        service.credit_tokens(
            user_id=user_id,
            amount=50,
            transaction_type=TokenTransactionType.PURCHASE,
        )

        assert balance_mock.balance == 60
        session.add.assert_any_call(balance_mock)
        session.commit.assert_called_once()
        assert _added_transaction(session).amount == 50

    def test_credit_tokens_rejects_non_positive(self):
        """credit_tokens raises ValueError for non-positive amount."""
        from vbwd.services.token_service import TokenService
        import pytest

        session = MagicMock()
        service = TokenService(
            balance_repo=MagicMock(),
            transaction_repo=MagicMock(),
            purchase_repo=MagicMock(),
            session=session,
        )

        with pytest.raises(ValueError, match="positive"):
            service.credit_tokens(
                user_id=uuid4(),
                amount=0,
                transaction_type=TokenTransactionType.PURCHASE,
            )

        session.rollback.assert_not_called()


class TestTokenServiceDebitTokens:
    """Tests for TokenService.debit_tokens()."""

    def test_debit_tokens_raises_on_insufficient_balance(self):
        """debit_tokens raises ValueError when balance insufficient."""
        from vbwd.services.token_service import TokenService
        import pytest

        session = MagicMock()
        balance_repo = MagicMock()
        balance_repo.find_by_user_id.return_value = MagicMock(balance=10)

        service = TokenService(
            balance_repo=balance_repo,
            transaction_repo=MagicMock(),
            purchase_repo=MagicMock(),
            session=session,
        )

        with pytest.raises(ValueError, match="Insufficient"):
            service.debit_tokens(
                user_id=uuid4(),
                amount=50,
                transaction_type=TokenTransactionType.USAGE,
            )

        session.rollback.assert_not_called()

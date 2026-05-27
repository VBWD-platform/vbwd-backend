"""S16 — TokenBalanceRepository + TokenTransactionRepository contract tests."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.user_token_balance import TokenTransaction, UserTokenBalance
from vbwd.repositories.token_repository import (
    TokenBalanceRepository,
    TokenTransactionRepository,
)


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def balance_repo(session):
    return TokenBalanceRepository(session)


@pytest.fixture
def transaction_repo(session):
    return TokenTransactionRepository(session)


def test_balance_find_by_user_id_returns_first(session, balance_repo):
    sentinel = object()
    session.query.return_value.filter.return_value.first.return_value = sentinel
    assert balance_repo.find_by_user_id(uuid4()) is sentinel
    session.query.assert_called_with(UserTokenBalance)


def test_balance_find_by_user_id_returns_none(session, balance_repo):
    session.query.return_value.filter.return_value.first.return_value = None
    assert balance_repo.find_by_user_id(uuid4()) is None


def test_balance_get_or_create_returns_existing(session, balance_repo):
    sentinel = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = sentinel
    result = balance_repo.get_or_create(uuid4())
    assert result is sentinel
    session.add.assert_not_called()


def test_balance_get_or_create_creates_when_missing(session, balance_repo):
    session.query.return_value.filter.return_value.first.return_value = None
    result = balance_repo.get_or_create(uuid4())
    session.add.assert_called_once()
    assert isinstance(result, UserTokenBalance)


def test_transaction_find_by_reference_id(session, transaction_repo):
    sentinel = object()
    session.query.return_value.filter.return_value.first.return_value = sentinel
    assert transaction_repo.find_by_reference_id(uuid4()) is sentinel
    session.query.assert_called_with(TokenTransaction)

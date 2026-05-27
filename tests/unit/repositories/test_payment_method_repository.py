"""S16 — PaymentMethodRepository contract tests."""
from unittest.mock import MagicMock

import pytest

from vbwd.models import PaymentMethod
from vbwd.repositories.payment_method_repository import PaymentMethodRepository


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def repository(session):
    return PaymentMethodRepository(session)


def test_find_by_code_returns_first_match(session, repository):
    sentinel = object()
    session.query.return_value.filter.return_value.first.return_value = sentinel
    assert repository.find_by_code("stripe") is sentinel
    session.query.assert_called_with(PaymentMethod)


def test_find_by_code_returns_none_when_absent(session, repository):
    session.query.return_value.filter.return_value.first.return_value = None
    assert repository.find_by_code("missing") is None


def test_find_active_returns_list(session, repository):
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
        []
    )
    assert repository.find_active() == []


def test_find_default_returns_first(session, repository):
    sentinel = object()
    session.query.return_value.filter.return_value.first.return_value = sentinel
    assert repository.find_default() is sentinel


def test_code_exists_returns_true_when_match_found(session, repository):
    """``code_exists`` uses ``query.first() is not None``, not ``count``."""
    session.query.return_value.filter.return_value.first.return_value = MagicMock()
    assert repository.code_exists("stripe") is True


def test_code_exists_returns_false_when_no_match(session, repository):
    session.query.return_value.filter.return_value.first.return_value = None
    assert repository.code_exists("not-there") is False

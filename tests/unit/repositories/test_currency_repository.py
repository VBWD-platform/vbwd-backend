"""S16 — CurrencyRepository contract tests."""
from unittest.mock import MagicMock

import pytest

from vbwd.models import Currency
from vbwd.repositories.currency_repository import CurrencyRepository


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def repository(session):
    return CurrencyRepository(session)


def test_find_by_code_filters_on_code(session, repository):
    sentinel = object()
    session.query.return_value.filter_by.return_value.first.return_value = sentinel
    assert repository.find_by_code("USD") is sentinel
    session.query.assert_called_once_with(Currency)


def test_find_default_returns_first_default(session, repository):
    sentinel = object()
    session.query.return_value.filter_by.return_value.first.return_value = sentinel
    assert repository.find_default() is sentinel


def test_find_active_returns_filtered_list(session, repository):
    session.query.return_value.filter_by.return_value.all.return_value = ["usd", "eur"]
    assert repository.find_active() == ["usd", "eur"]


def test_find_by_code_returns_none_when_absent(session, repository):
    session.query.return_value.filter_by.return_value.first.return_value = None
    assert repository.find_by_code("XYZ") is None

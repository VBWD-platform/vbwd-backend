"""S16 / S84 — CurrencyRepository contract tests."""
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


def test_find_by_code_returns_none_when_absent(session, repository):
    session.query.return_value.filter_by.return_value.first.return_value = None
    assert repository.find_by_code("XYZ") is None


def test_list_all_returns_ordered_catalog(session, repository):
    session.query.return_value.order_by.return_value.all.return_value = ["eur", "usd"]
    assert repository.list_all() == ["eur", "usd"]
    session.query.assert_called_once_with(Currency)


def test_delete_by_code_deletes_existing_row(session, repository):
    row = object()
    session.query.return_value.filter_by.return_value.first.return_value = row
    assert repository.delete_by_code("GBP") is True
    session.delete.assert_called_once_with(row)
    session.commit.assert_called_once()


def test_delete_by_code_returns_false_when_absent(session, repository):
    session.query.return_value.filter_by.return_value.first.return_value = None
    assert repository.delete_by_code("XYZ") is False
    session.delete.assert_not_called()

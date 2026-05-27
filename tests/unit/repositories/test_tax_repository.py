"""S16 — TaxRepository contract tests."""
from unittest.mock import MagicMock

import pytest

from vbwd.models import Tax
from vbwd.repositories.tax_repository import TaxRepository


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def repository(session):
    return TaxRepository(session)


def test_find_by_code_returns_first(session, repository):
    sentinel = object()
    session.query.return_value.filter_by.return_value.first.return_value = sentinel
    assert repository.find_by_code("VAT-DE") is sentinel
    session.query.assert_called_with(Tax)


def test_find_by_code_returns_none_when_absent(session, repository):
    session.query.return_value.filter_by.return_value.first.return_value = None
    assert repository.find_by_code("nope") is None


def test_find_by_country_returns_list(session, repository):
    session.query.return_value.filter_by.return_value.all.return_value = ["vat"]
    assert repository.find_by_country("DE") == ["vat"]


def test_find_active_returns_list(session, repository):
    session.query.return_value.filter_by.return_value.all.return_value = []
    assert repository.find_active() == []

"""S16 — CountryRepository contract tests."""
from unittest.mock import MagicMock

import pytest

from vbwd.models import Country
from vbwd.repositories.country_repository import CountryRepository


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def repository(session):
    return CountryRepository(session)


def test_find_by_code_filters_on_code(session, repository):
    sentinel = object()
    session.query.return_value.filter.return_value.first.return_value = sentinel
    assert repository.find_by_code("US") is sentinel
    session.query.assert_called_once_with(Country)


def test_find_by_code_returns_none_when_absent(session, repository):
    session.query.return_value.filter.return_value.first.return_value = None
    assert repository.find_by_code("ZZ") is None


def test_find_all_ordered_invokes_query_with_country(session, repository):
    session.query.return_value.order_by.return_value.all.return_value = []
    repository.find_all_ordered()
    session.query.assert_called_once_with(Country)


def test_find_enabled_returns_filtered_list(session, repository):
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        "us",
        "ca",
    ]
    assert repository.find_enabled() == ["us", "ca"]

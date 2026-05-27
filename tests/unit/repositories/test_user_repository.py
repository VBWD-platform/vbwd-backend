"""S16 worked example — UserRepository contract tests.

Repository tests verify query-construction wiring. The standing project
convention (CLAUDE.md "Test Pattern") is unit tests use MagicMock for
the session; integration tests exercise real PostgreSQL via the
``tests/integration/`` suite. These tests cover the unit layer for
``UserRepository`` and are the template for the rest of the S16 backlog
(see ``tests/meta/test_repository_coverage.py::EXPECTED_GAPS``).
"""
from unittest.mock import MagicMock

import pytest

from vbwd.models import User
from vbwd.repositories.user_repository import UserRepository


@pytest.fixture
def session():
    """A MagicMock session that returns chainable mocks for query()/filter()/first()."""
    return MagicMock()


@pytest.fixture
def repository(session):
    return UserRepository(session)


def test_find_by_email_filters_on_email_column(session, repository):
    repository.find_by_email("user@example.com")
    session.query.assert_called_once_with(User)
    session.query.return_value.filter.assert_called_once()
    session.query.return_value.filter.return_value.first.assert_called_once()


def test_find_by_email_returns_first_match(session, repository):
    expected_user = object()  # sentinel, no need for User spec
    session.query.return_value.filter.return_value.first.return_value = expected_user

    result = repository.find_by_email("user@example.com")

    assert result is expected_user


def test_find_by_email_returns_none_when_no_match(session, repository):
    session.query.return_value.filter.return_value.first.return_value = None
    assert repository.find_by_email("nope@example.com") is None


def test_email_exists_returns_true_when_count_positive(session, repository):
    session.query.return_value.filter.return_value.count.return_value = 1
    assert repository.email_exists("taken@example.com") is True


def test_email_exists_returns_false_when_count_zero(session, repository):
    session.query.return_value.filter.return_value.count.return_value = 0
    assert repository.email_exists("free@example.com") is False


def test_find_by_status_applies_status_filter(session, repository):
    session.query.return_value.filter.return_value.all.return_value = []
    repository.find_by_status("ACTIVE")
    session.query.assert_called_once_with(User)
    session.query.return_value.filter.return_value.all.assert_called_once()


def test_find_all_paginated_returns_total_count(session, repository):
    """Pagination returns the unbounded count plus a (potentially-limited) list."""
    session.query.return_value.count.return_value = 42
    # We don't pin the order_by/offset/limit chain — repos may legitimately
    # reorder those calls; the contract is "returns (list, count)".
    _, total = repository.find_all_paginated(limit=10, offset=20)
    assert total == 42

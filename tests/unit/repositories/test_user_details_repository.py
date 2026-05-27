"""S16 — UserDetailsRepository contract tests."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models import UserDetails
from vbwd.repositories.user_details_repository import UserDetailsRepository


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def repository(session):
    return UserDetailsRepository(session)


def test_find_by_user_id_returns_first(session, repository):
    sentinel = object()
    session.query.return_value.filter_by.return_value.first.return_value = sentinel
    assert repository.find_by_user_id(uuid4()) is sentinel
    session.query.assert_called_with(UserDetails)


def test_find_by_user_id_returns_none_when_absent(session, repository):
    session.query.return_value.filter_by.return_value.first.return_value = None
    assert repository.find_by_user_id(uuid4()) is None


def test_save_persists_via_session(session, repository):
    details = MagicMock()
    saved = repository.save(details)
    session.add.assert_called_once_with(details)
    assert saved is details

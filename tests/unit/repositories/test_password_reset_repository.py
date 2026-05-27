"""S16 — PasswordResetRepository contract tests."""
from unittest.mock import MagicMock

import pytest

from vbwd.models import PasswordResetToken
from vbwd.repositories.password_reset_repository import PasswordResetRepository


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def repository(session):
    return PasswordResetRepository(session)


def test_find_by_token_returns_first_match(session, repository):
    sentinel = object()
    session.query.return_value.filter.return_value.first.return_value = sentinel
    assert repository.find_by_token("token-abc") is sentinel
    session.query.assert_called_once_with(PasswordResetToken)


def test_find_by_token_returns_none_when_absent(session, repository):
    session.query.return_value.filter.return_value.first.return_value = None
    assert repository.find_by_token("missing") is None


def test_save_persists_via_session(session, repository):
    token = MagicMock()
    saved = repository.save(token)
    session.add.assert_called_once_with(token)
    assert saved is token

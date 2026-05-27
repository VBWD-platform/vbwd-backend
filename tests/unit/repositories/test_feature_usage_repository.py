"""S16 — FeatureUsageRepository contract tests (BaseRepository-only surface)."""
from unittest.mock import MagicMock

import pytest

from vbwd.models import FeatureUsage
from vbwd.repositories.feature_usage_repository import FeatureUsageRepository


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def repository(session):
    return FeatureUsageRepository(session)


def test_repository_constructs_with_session(session, repository):
    assert repository is not None


def test_find_by_id_uses_session_get(session, repository):
    """BaseRepository.find_by_id uses session.get(model, id) (SQLAlchemy 2.x)."""
    sentinel = object()
    session.get.return_value = sentinel
    assert repository.find_by_id("usage-1") is sentinel
    session.get.assert_called_once_with(FeatureUsage, "usage-1")


def test_save_persists_via_session(session, repository):
    entity = MagicMock()
    saved = repository.save(entity)
    session.add.assert_called_once_with(entity)
    assert saved is entity

"""S16 — TokenBundleRepository contract tests."""
from unittest.mock import MagicMock

import pytest

from vbwd.models import TokenBundle
from vbwd.repositories.token_bundle_repository import TokenBundleRepository


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def repository(session):
    return TokenBundleRepository(session)


def test_find_active_queries_token_bundle(session, repository):
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
        []
    )
    repository.find_active()
    session.query.assert_called_with(TokenBundle)


def test_find_all_paginated_returns_total_count(session, repository):
    """Contract: ``find_all_paginated(page, per_page, include_inactive)``
    returns ``(bundles_list, total_count)``."""
    session.query.return_value.count.return_value = 7
    _, total = repository.find_all_paginated(page=1, per_page=10)
    assert total == 7


def test_save_persists_via_session(session, repository):
    bundle = MagicMock()
    saved = repository.save(bundle)
    session.add.assert_called_once_with(bundle)
    assert saved is bundle

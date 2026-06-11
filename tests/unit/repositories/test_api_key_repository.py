"""S52.0 — core ``ApiKeyRepository`` unit tests (MagicMock session)."""
from unittest.mock import MagicMock
from uuid import uuid4

from vbwd.models.api_key import ApiKey
from vbwd.repositories.api_key_repository import ApiKeyRepository


def _repo_with_query_result(result):
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value = query
    query.filter_by.return_value = query
    query.order_by.return_value = query
    query.first.return_value = result
    query.all.return_value = result if isinstance(result, list) else [result]
    return ApiKeyRepository(session), session, query


def test_find_by_hash_filters_on_key_hash():
    api_key = ApiKey()
    repo, session, query = _repo_with_query_result(api_key)

    found = repo.find_by_hash("a" * 64)

    assert found is api_key
    session.query.assert_called_once_with(ApiKey)


def test_find_by_user_returns_list():
    api_key = ApiKey()
    repo, session, query = _repo_with_query_result([api_key])

    found = repo.find_by_user(uuid4())

    assert found == [api_key]


def test_revoke_sets_is_active_false_and_commits():
    api_key = ApiKey()
    api_key.is_active = True
    session = MagicMock()
    repo = ApiKeyRepository(session)
    repo.find_by_id = MagicMock(return_value=api_key)  # type: ignore[method-assign]

    result = repo.revoke(uuid4())

    assert result is True
    assert api_key.is_active is False
    session.commit.assert_called_once()


def test_revoke_missing_key_returns_false():
    session = MagicMock()
    repo = ApiKeyRepository(session)
    repo.find_by_id = MagicMock(return_value=None)  # type: ignore[method-assign]

    assert repo.revoke(uuid4()) is False


def test_save_adds_and_commits():
    session = MagicMock()
    repo = ApiKeyRepository(session)
    api_key = ApiKey()

    repo.save(api_key)

    session.commit.assert_called()

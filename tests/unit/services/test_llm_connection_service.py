"""RED tests for LlmConnectionService (S97.1).

MagicMock repository (no DB). Asserts the single-default invariant, the
active-default rule (D-DefaultActive), by-slug resolution, masking, and the
``llm_client`` resolver building a real LlmClient over ``select_adapter``.
"""
from unittest.mock import MagicMock

import pytest

from vbwd.llm.client import LlmClient
from vbwd.models.llm_connection import LlmConnection
from vbwd.services.llm_connection_service import (
    LlmConnectionService,
    NoActiveLlmConnectionError,
)


def _connection(**overrides) -> LlmConnection:
    defaults = dict(
        slug="default-claude",
        connection_name="Default Claude",
        api_endpoint="https://api.anthropic.com",
        api_key="sk-ant-0123456789abcdefXYZ",
        model="claude-3-5-sonnet-latest",
        is_active=True,
        is_default=True,
    )
    defaults.update(overrides)
    connection = LlmConnection(**defaults)
    if "id" not in overrides:
        connection.id = overrides.get("id", "11111111-1111-1111-1111-111111111111")
    return connection


def _service(repo):
    return LlmConnectionService(repository=repo)


def test_mask_reveals_exactly_sixteen_chars():
    repo = MagicMock()
    service = _service(repo)
    masked = service.mask("0123456789abcdefGHIJKL")
    assert masked.startswith("0123456789abcdef")
    assert masked == "0123456789abcdef" + "…"
    # exactly 16 revealed
    assert masked[:16] == "0123456789abcdef"


def test_set_default_flips_previous_default_off():
    previous = _connection(id="prev", slug="prev", is_default=True, is_active=True)
    target = _connection(id="target", slug="target", is_default=False, is_active=True)
    repo = MagicMock()
    repo.find_by_id.return_value = target
    repo.find_default.return_value = previous
    service = _service(repo)

    service.set_default("target")

    assert target.is_default is True
    assert previous.is_default is False


def test_set_default_requires_active_target():
    target = _connection(id="t", slug="t", is_active=False, is_default=False)
    repo = MagicMock()
    repo.find_by_id.return_value = target
    repo.find_default.return_value = None
    service = _service(repo)

    with pytest.raises(ValueError):
        service.set_default("t")


def test_get_default_returns_active_default():
    default = _connection(is_active=True, is_default=True)
    repo = MagicMock()
    repo.find_default.return_value = default
    service = _service(repo)

    assert service.get_default() is default


def test_get_default_ignores_inactive_default():
    default = _connection(is_active=False, is_default=True)
    repo = MagicMock()
    repo.find_default.return_value = default
    service = _service(repo)

    assert service.get_default() is None


def test_get_by_slug_delegates_to_repo():
    connection = _connection(slug="my-slug")
    repo = MagicMock()
    repo.find_by_slug.return_value = connection
    service = _service(repo)

    assert service.get_by_slug("my-slug") is connection
    repo.find_by_slug.assert_called_once_with("my-slug")


def test_deactivating_default_clears_default():
    default = _connection(id="d", slug="d", is_active=True, is_default=True)
    repo = MagicMock()
    repo.find_by_ids.return_value = [default]
    service = _service(repo)

    service.set_active(["d"], False)

    assert default.is_active is False
    assert default.is_default is False


def test_deleting_default_clears_default():
    default = _connection(id="d", slug="d", is_active=True, is_default=True)
    repo = MagicMock()
    repo.find_by_id.return_value = default
    service = _service(repo)

    service.delete("d")

    repo.delete.assert_called_once_with("d")


def test_llm_client_by_slug_resolves_that_connection():
    openai_conn = _connection(
        slug="openai", model="gpt-4o-mini", api_endpoint="https://api.openai.com/v1"
    )
    repo = MagicMock()
    repo.find_by_slug.return_value = openai_conn
    service = _service(repo)

    client = service.llm_client(slug="openai")

    assert isinstance(client, LlmClient)


def test_llm_client_none_resolves_default():
    default = _connection(is_active=True, is_default=True)
    repo = MagicMock()
    repo.find_default.return_value = default
    service = _service(repo)

    client = service.llm_client(None)

    assert isinstance(client, LlmClient)


def test_llm_client_raises_when_no_active_connection():
    repo = MagicMock()
    repo.find_default.return_value = None
    service = _service(repo)

    with pytest.raises(NoActiveLlmConnectionError):
        service.llm_client(None)


def test_llm_client_raises_when_slug_inactive():
    inactive = _connection(slug="x", is_active=False, is_default=False)
    repo = MagicMock()
    repo.find_by_slug.return_value = inactive
    service = _service(repo)

    with pytest.raises(NoActiveLlmConnectionError):
        service.llm_client(slug="x")


def test_stamp_last_active_updates_connection():
    connection = _connection()
    repo = MagicMock()
    repo.find_by_id.return_value = connection
    service = _service(repo)

    service.stamp_last_active("11111111-1111-1111-1111-111111111111")

    assert connection.last_active_at is not None
    repo.update.assert_called_once()

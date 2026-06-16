"""Unit tests for the llm_connections exchanger (S97.2).

Asserts the two D-ExportKey guarantees with a fake repo/session (no DB):
export OMITS the api_key; import lands the connection ``is_active=False`` with
no live key. Uses the real ``LlmConnection`` model so the column shape is real.
"""
from typing import List, Optional

from vbwd.models.llm_connection import LlmConnection
from vbwd.services.data_exchange.core_exchangers import (
    _build_llm_connections_exchanger,
)
from vbwd.services.data_exchange.port import MODE_UPSERT, ExportSelector


class _FakeRepo:
    def __init__(self, rows: Optional[List[LlmConnection]] = None):
        self._rows = {row.slug: row for row in (rows or [])}

    def find_all(self) -> List[LlmConnection]:
        return list(self._rows.values())

    def iter_rows(self, batch_size: int = 5000):
        for row in list(self._rows.values()):
            yield row

    def find_by_natural_key(self, value):
        return self._rows.get(value)

    def add(self, instance):
        self._rows[instance.slug] = instance

    def delete_all(self):
        self._rows.clear()


class _FakeSession:
    def commit(self):
        pass

    def rollback(self):
        pass

    def flush(self):
        pass


def _make(rows=None):
    exchanger = _build_llm_connections_exchanger(_FakeSession())
    exchanger._repository = _FakeRepo(rows)
    exchanger._session = _FakeSession()
    return exchanger


def _connection(slug, *, active=True, default=False):
    conn = LlmConnection(
        slug=slug,
        connection_name=f"Conn {slug}",
        api_endpoint="https://api.anthropic.com",
        api_key="sk-ant-super-secret-live-key-value",
        model="claude-3-5-sonnet-latest",
        is_active=active,
        is_default=default,
    )
    return conn


def test_export_omits_api_key():
    exchanger = _make([_connection("a"), _connection("b")])
    rows = exchanger.export(ExportSelector(all=True), include_pii=True).rows
    assert rows, "expected exported rows"
    for row in rows:
        assert "api_key" not in row
    assert rows[0]["slug"] == "a"


def test_import_lands_connection_inactive():
    exchanger = _make([])
    payload = {
        "vbwd_export": "llm_connections",
        "llm_connections": [
            {
                "slug": "imported",
                "connection_name": "Imported",
                "api_endpoint": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "is_active": True,
                "is_default": True,
            }
        ],
    }
    result = exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
    assert result.created == 1

    landed = exchanger._repository.find_by_natural_key("imported")
    assert landed is not None
    assert landed.is_active is False
    assert landed.is_default is False
    # A placeholder key is set (NOT NULL satisfied) but it is never the live key.
    assert landed.api_key
    assert "secret" not in landed.api_key

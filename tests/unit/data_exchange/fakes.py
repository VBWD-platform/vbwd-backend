"""Shared fakes for data-exchange unit tests.

No real entity is used in S46.0 — these throwaway helpers stand in for a
plugin/core exchanger so the generic seam (registry, routes, base exchanger,
permission catalog) can be exercised end-to-end without any domain model.
"""
from types import SimpleNamespace
from typing import List, Optional

from vbwd.services.data_exchange.port import (
    EntityExchanger,
    Envelope,
    ExportSelector,
    ImportResult,
    UnsupportedOperationError,
)


class FakeRecord:
    """A throwaway model row: a public natural key, a secret, and a PII field."""

    def __init__(
        self,
        code: str = "",
        label: str = "",
        secret: str = "",
        owner_email: str = "",
    ):
        self.id = None
        self.code = code
        self.label = label
        self.secret = secret
        self.owner_email = owner_email

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "label": self.label,
            "secret": self.secret,
            "owner_email": self.owner_email,
        }


class FakeRepository:
    """In-memory repo keyed by ``code`` — no DB, mirrors the upsert contract."""

    def __init__(self, rows: Optional[List[FakeRecord]] = None):
        self._rows: dict = {row.code: row for row in (rows or [])}
        self.committed = False

    def find_all(self) -> List[FakeRecord]:
        return list(self._rows.values())

    def find_by_natural_key(self, value: str) -> Optional[FakeRecord]:
        return self._rows.get(value)

    def add(self, row: FakeRecord) -> None:
        self._rows[row.code] = row

    def delete_all(self) -> None:
        self._rows.clear()


class FakeSession:
    """Minimal session capturing commit / rollback for dry-run assertions."""

    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class FakeExportOnlyExchanger(EntityExchanger):
    """Export-only exchanger — ``import_`` must raise (Liskov)."""

    entity_key = "fake_reports"
    label = "Fake Reports"
    cluster = "sales"
    natural_key = "code"
    supports_export = True
    supports_import = False
    supported_formats = frozenset({"json"})
    secret_fields = frozenset()
    pii_fields = frozenset()

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        return Envelope(entity_key=self.entity_key, rows=[{"code": "r1"}])

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        raise UnsupportedOperationError(f"{self.entity_key} does not support import")


def make_user(*, superadmin: bool = False, permissions: Optional[List[str]] = None):
    """A fake current_user with the permission contract the registry relies on."""
    granted = set(permissions or [])

    def has_permission(name: str) -> bool:
        return superadmin or name in granted

    return SimpleNamespace(
        is_admin=True,
        role=SimpleNamespace(value="SUPER_ADMIN" if superadmin else "ADMIN"),
        has_permission=has_permission,
    )

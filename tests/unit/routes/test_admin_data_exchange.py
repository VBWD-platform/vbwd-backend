"""Unit tests for the generic data-exchange admin routes.

S46.0 ships no real exchanger, so these tests register a FAKE exchanger over
an in-memory repo into the module-level registry singleton, exercise every
route, then clear it.
"""
import io
import json
import zipfile
from unittest.mock import patch
from uuid import uuid4

import pytest

from vbwd.models.enums import UserRole
from vbwd.services.data_exchange.envelope import build_envelope
from vbwd.services.data_exchange.port import (
    Envelope,
    ExportSelector,
    ImportResult,
    UnsupportedOperationError,
)
from vbwd.services.data_exchange.registry import data_exchange_registry

from tests.fixtures.access import (
    make_user_no_permissions,
    make_user_with_permissions,
)
from vbwd.services.data_exchange.port import EntityExchanger


class _FakeWidgetExchanger(EntityExchanger):
    entity_key = "widgets"
    label = "Widgets"
    cluster = "sales"
    natural_key = "code"
    supports_export = True
    supports_import = True
    supported_formats = frozenset({"json", "csv"})
    secret_fields = frozenset()
    pii_fields = frozenset({"owner_email"})

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        row = {"code": "a", "label": "Alpha", "owner_email": None}
        if include_pii:
            row["owner_email"] = "alice@example.com"
        return Envelope(entity_key="widgets", rows=[row])

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        rows = payload.get("widgets", [])
        return ImportResult(
            entity="widgets",
            mode=mode,
            dry_run=dry_run,
            created=len(rows),
        )


@pytest.fixture(autouse=True)
def _registered_widget():
    data_exchange_registry.register(_FakeWidgetExchanger())
    yield
    data_exchange_registry.clear()


def _headers():
    return {"Authorization": "Bearer valid"}


def _mock_auth(mock_repo_cls, mock_auth_cls, user):
    mock_repo_cls.return_value.find_by_id.return_value = user
    mock_auth_cls.return_value.verify_token.return_value = str(uuid4())


def _superadmin():
    user = make_user_with_permissions()
    user.role = UserRole.SUPER_ADMIN
    user.has_permission = lambda pn: True
    return user


# ── manifest ─────────────────────────────────────────────────────────────


def test_manifest_unauthenticated(client):
    response = client.get("/api/v1/admin/data-exchange/manifest")
    assert response.status_code == 401


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_manifest_returns_clustered_entities(mock_repo, mock_auth, client):
    _mock_auth(mock_repo, mock_auth, _superadmin())
    response = client.get("/api/v1/admin/data-exchange/manifest", headers=_headers())
    assert response.status_code == 200
    entities = response.get_json()["entities"]
    assert any(item["entity_key"] == "widgets" for item in entities)


# ── single export ────────────────────────────────────────────────────────


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_export_forbidden_without_permission(mock_repo, mock_auth, client):
    _mock_auth(mock_repo, mock_auth, make_user_no_permissions())
    response = client.post(
        "/api/v1/admin/data-exchange/widgets/export",
        headers=_headers(),
        json={"all": True},
    )
    assert response.status_code == 403


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_export_redacts_pii_without_pii_permission(mock_repo, mock_auth, client):
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("widgets.export"))
    response = client.post(
        "/api/v1/admin/data-exchange/widgets/export",
        headers=_headers(),
        json={"all": True},
    )
    assert response.status_code == 200
    rows = response.get_json()["widgets"]
    assert rows[0]["owner_email"] is None


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_export_selected_by_ids_returns_non_empty(mock_repo, mock_auth, client):
    """POST /export {ids:[...]} flows the selector ids through to the exchanger;
    the envelope is non-empty with exactly the selected rows (the empty-export
    bug surfaced here from the UI sending primary ids)."""

    class _IdAwareExchanger(EntityExchanger):
        entity_key = "widgets"
        label = "Widgets"
        cluster = "sales"
        natural_key = "code"
        supports_export = True
        supports_import = False
        supported_formats = frozenset({"json"})
        secret_fields = frozenset()
        pii_fields = frozenset()

        _ROWS = [
            {"id": "uuid-a", "code": "a"},
            {"id": "uuid-b", "code": "b"},
        ]

        def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
            rows = self._ROWS
            if selector.ids:
                wanted = {str(value) for value in selector.ids}
                rows = [
                    row for row in rows if row["id"] in wanted or row["code"] in wanted
                ]
            return Envelope(entity_key="widgets", rows=rows)

        def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
            raise UnsupportedOperationError("widgets is export-only")

    data_exchange_registry.register(_IdAwareExchanger())
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("widgets.export"))
    response = client.post(
        "/api/v1/admin/data-exchange/widgets/export",
        headers=_headers(),
        json={"ids": ["uuid-b"]},
    )
    assert response.status_code == 200
    rows = response.get_json()["widgets"]
    assert [row["code"] for row in rows] == ["b"]


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_export_includes_pii_with_pii_permission(mock_repo, mock_auth, client):
    _mock_auth(
        mock_repo,
        mock_auth,
        make_user_with_permissions("widgets.export", "widgets.export.pii"),
    )
    response = client.post(
        "/api/v1/admin/data-exchange/widgets/export",
        headers=_headers(),
        json={"all": True},
    )
    assert response.status_code == 200
    rows = response.get_json()["widgets"]
    assert rows[0]["owner_email"] == "alice@example.com"


# ── single import ────────────────────────────────────────────────────────


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_import_forbidden_without_permission(mock_repo, mock_auth, client):
    _mock_auth(mock_repo, mock_auth, make_user_no_permissions())
    response = client.post(
        "/api/v1/admin/data-exchange/widgets/import",
        headers=_headers(),
        json={"payload": {"widgets": []}, "mode": "upsert", "dry_run": True},
    )
    assert response.status_code == 403


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_import_upsert_returns_result(mock_repo, mock_auth, client):
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("widgets.import"))
    response = client.post(
        "/api/v1/admin/data-exchange/widgets/import",
        headers=_headers(),
        json={
            "payload": {"widgets": [{"code": "x"}]},
            "mode": "upsert",
            "dry_run": True,
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["created"] == 1
    assert body["dry_run"] is True


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_import_replace_all_forbidden_for_non_superadmin(mock_repo, mock_auth, client):
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("widgets.import"))
    response = client.post(
        "/api/v1/admin/data-exchange/widgets/import",
        headers=_headers(),
        json={
            "payload": {"widgets": []},
            "mode": "replace_all",
            "dry_run": False,
        },
    )
    assert response.status_code == 403


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_import_replace_all_allowed_for_superadmin(mock_repo, mock_auth, client):
    _mock_auth(mock_repo, mock_auth, _superadmin())
    response = client.post(
        "/api/v1/admin/data-exchange/widgets/import",
        headers=_headers(),
        json={
            "payload": {"widgets": []},
            "mode": "replace_all",
            "dry_run": False,
        },
    )
    assert response.status_code == 200


# ── bundle export / import ───────────────────────────────────────────────


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_bundle_export_drops_unpermitted(mock_repo, mock_auth, client):
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("widgets.export"))
    response = client.post(
        "/api/v1/admin/data-exchange/export",
        headers=_headers(),
        json={"entities": ["widgets", "nope_unknown"]},
    )
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.data))
    names = archive.namelist()
    assert "manifest.json" in names
    assert "widgets.json" in names
    manifest = json.loads(archive.read("manifest.json"))
    assert any(c["entity_key"] == "widgets" for c in manifest["contents"])


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_bundle_import_round_trip(mock_repo, mock_auth, client):
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("widgets.import"))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "instance": "main",
                    "version": 1,
                    "contents": [
                        {"entity_key": "widgets", "file": "widgets.json", "version": 1}
                    ],
                }
            ),
        )
        archive.writestr(
            "widgets.json",
            json.dumps(build_envelope("widgets", [{"code": "z"}], instance="main")),
        )
    buffer.seek(0)

    response = client.post(
        "/api/v1/admin/data-exchange/import",
        headers=_headers(),
        data={
            "file": (buffer, "bundle.zip"),
            "mode": "upsert",
            "dry_run": "true",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    results = response.get_json()["results"]
    assert results[0]["entity"] == "widgets"
    assert results[0]["created"] == 1


def test_unsupported_operation_error_is_importable():
    """Sanity: the export-only Liskov exception type is exported by the port."""
    assert issubclass(UnsupportedOperationError, Exception)

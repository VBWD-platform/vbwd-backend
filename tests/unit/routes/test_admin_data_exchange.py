"""Unit tests for the generic data-exchange admin routes.

S46.0 ships no real exchanger, so these tests register a FAKE exchanger over
an in-memory repo into the module-level registry singleton, exercise every
route, then clear it.
"""
import base64
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


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_export_zip_returns_valid_archive_with_assets(mock_repo, mock_auth, client):
    """A zip-capable exchanger exporting ``format=zip`` returns a real ZIP whose
    ``assets/`` holds the binary bytes and whose ``<key>.json`` holds the rows."""

    class _ZipExchanger(EntityExchanger):
        entity_key = "pics"
        label = "Pics"
        cluster = "sales"
        natural_key = "slug"
        supports_export = True
        supports_import = False
        supported_formats = frozenset({"json", "zip"})
        secret_fields = frozenset()
        pii_fields = frozenset()

        def export(self, selector, *, include_pii):
            return Envelope(entity_key="pics", rows=[{"slug": "a", "data": "ZA=="}])

        def export_zip(self, selector, *, include_pii):
            from vbwd.services.data_exchange.port import ZipExport

            return ZipExport(
                rows=[{"slug": "a", "asset_file": "a.png"}],
                assets={"a.png": b"raw-bytes"},
            )

        def import_(self, payload, *, mode, dry_run):
            raise UnsupportedOperationError("pics is export-only")

    data_exchange_registry.register(_ZipExchanger())
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("pics.export"))
    response = client.post(
        "/api/v1/admin/data-exchange/pics/export",
        headers=_headers(),
        json={"all": True, "format": "zip"},
    )
    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.data))
    names = archive.namelist()
    assert "manifest.json" in names
    assert "pics.json" in names
    assert "assets/a.png" in names
    assert archive.read("assets/a.png") == b"raw-bytes"
    rows = json.loads(archive.read("pics.json"))["pics"]
    assert rows[0]["asset_file"] == "a.png"


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_export_zip_unsupported_entity_returns_400(mock_repo, mock_auth, client):
    """``widgets`` advertises only json/csv → asking for zip is a clear 400."""
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("widgets.export"))
    response = client.post(
        "/api/v1/admin/data-exchange/widgets/export",
        headers=_headers(),
        json={"all": True, "format": "zip"},
    )
    assert response.status_code == 400


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
def test_import_unexpected_error_returns_422_not_500(mock_repo, mock_auth, client):
    """A bad/foreign import file is user input: an unexpected exception from the
    exchanger (a DB IntegrityError, a TypeError from an odd row key, …) must come
    back as a structured 422 the fe can surface — never an opaque unhandled 500.
    The full traceback is logged (Fix 1 makes that diagnosable)."""

    class _BoomImportExchanger(EntityExchanger):
        entity_key = "widgets"
        label = "Widgets"
        cluster = "sales"
        natural_key = "code"
        supports_export = False
        supports_import = True
        supported_formats = frozenset({"json"})
        secret_fields = frozenset()
        pii_fields = frozenset()

        def export(self, selector, *, include_pii):  # pragma: no cover - unused
            raise UnsupportedOperationError("widgets is import-only")

        def import_(self, payload, *, mode, dry_run):
            raise RuntimeError("boom")

    data_exchange_registry.register(_BoomImportExchanger())
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("widgets.import"))
    with patch("vbwd.routes.admin.data_exchange.current_app") as mock_current_app:
        response = client.post(
            "/api/v1/admin/data-exchange/widgets/import",
            headers=_headers(),
            json={"payload": {"widgets": [{"code": "x"}]}, "mode": "upsert"},
        )
    assert response.status_code == 422
    body = response.get_json()
    assert "widgets" in body["error"]
    assert "boom" in body["error"]
    mock_current_app.logger.exception.assert_called_once()


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_import_ndjson_unexpected_error_returns_422_not_500(
    mock_repo, mock_auth, client
):
    """The NDJSON streaming import path hardens the same way: an unexpected
    exchanger failure is a structured 422, not an unhandled 500."""

    class _BoomNdjsonExchanger(EntityExchanger):
        entity_key = "widgets"
        label = "Widgets"
        cluster = "sales"
        natural_key = "code"
        supports_export = False
        supports_import = True
        supported_formats = frozenset({"json", "ndjson"})
        secret_fields = frozenset()
        pii_fields = frozenset()

        def export(self, selector, *, include_pii):  # pragma: no cover - unused
            raise UnsupportedOperationError("widgets is import-only")

        def import_(self, payload, *, mode, dry_run):  # pragma: no cover - unused
            raise UnsupportedOperationError("use the ndjson path")

        def import_ndjson(self, lines, *, mode, dry_run, chunk_size):
            raise RuntimeError("ndjson boom")

    data_exchange_registry.register(_BoomNdjsonExchanger())
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("widgets.import"))
    ndjson = (
        json.dumps({"vbwd_export": "widgets", "version": 1, "format": "ndjson"})
        + "\n"
        + json.dumps({"code": "x"})
        + "\n"
    )
    with patch("vbwd.routes.admin.data_exchange.current_app") as mock_current_app:
        response = client.post(
            "/api/v1/admin/data-exchange/widgets/import",
            headers=_headers(),
            data={
                "file": (io.BytesIO(ndjson.encode("utf-8")), "widgets.ndjson"),
                "mode": "upsert",
                "format": "ndjson",
            },
            content_type="multipart/form-data",
        )
    assert response.status_code == 422
    assert "widgets" in response.get_json()["error"]
    mock_current_app.logger.exception.assert_called_once()


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_import_unsupported_operation_still_returns_400(mock_repo, mock_auth, client):
    """Regression: the Liskov export-only exception stays a 400, not the new
    422 unexpected-error path."""

    class _ExportOnlyExchanger(EntityExchanger):
        entity_key = "widgets"
        label = "Widgets"
        cluster = "sales"
        natural_key = "code"
        supports_export = True
        supports_import = True
        supported_formats = frozenset({"json"})
        secret_fields = frozenset()
        pii_fields = frozenset()

        def export(self, selector, *, include_pii):  # pragma: no cover - unused
            return Envelope(entity_key="widgets", rows=[])

        def import_(self, payload, *, mode, dry_run):
            raise UnsupportedOperationError("widgets rejects import")

    data_exchange_registry.register(_ExportOnlyExchanger())
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("widgets.import"))
    response = client.post(
        "/api/v1/admin/data-exchange/widgets/import",
        headers=_headers(),
        json={"payload": {"widgets": [{"code": "x"}]}, "mode": "upsert"},
    )
    assert response.status_code == 400


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_bundle_import_unexpected_error_is_per_entity_not_500(
    mock_repo, mock_auth, client
):
    """One bad entity in a multi-entity bundle must not 500 the whole import:
    an unexpected exchanger failure becomes that entity's ``errors:[{row:-1}]``
    result while the others still import."""

    class _BoomBundleExchanger(EntityExchanger):
        entity_key = "gadgets"
        label = "Gadgets"
        cluster = "sales"
        natural_key = "code"
        supports_export = False
        supports_import = True
        supported_formats = frozenset({"json"})
        secret_fields = frozenset()
        pii_fields = frozenset()

        def export(self, selector, *, include_pii):  # pragma: no cover - unused
            raise UnsupportedOperationError("gadgets is import-only")

        def import_(self, payload, *, mode, dry_run):
            raise RuntimeError("bundle boom")

    data_exchange_registry.register(_BoomBundleExchanger())
    _mock_auth(
        mock_repo,
        mock_auth,
        make_user_with_permissions("widgets.import", "gadgets.import"),
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "instance": "main",
                    "version": 1,
                    "contents": [
                        {"entity_key": "widgets", "file": "widgets.json", "version": 1},
                        {"entity_key": "gadgets", "file": "gadgets.json", "version": 1},
                    ],
                }
            ),
        )
        archive.writestr(
            "widgets.json",
            json.dumps(build_envelope("widgets", [{"code": "z"}], instance="main")),
        )
        archive.writestr(
            "gadgets.json",
            json.dumps(build_envelope("gadgets", [{"code": "g"}], instance="main")),
        )
    buffer.seek(0)

    with patch("vbwd.routes.admin.data_exchange.current_app") as mock_current_app:
        response = client.post(
            "/api/v1/admin/data-exchange/import",
            headers=_headers(),
            data={"file": (buffer, "bundle.zip"), "mode": "upsert"},
            content_type="multipart/form-data",
        )
    assert response.status_code == 200
    results = {item["entity"]: item for item in response.get_json()["results"]}
    assert results["widgets"]["created"] == 1
    assert results["gadgets"]["errors"][0]["row"] == -1
    assert "bundle boom" in results["gadgets"]["errors"][0]["reason"]
    mock_current_app.logger.exception.assert_called()


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


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_import_accepts_zip_upload_and_attaches_assets(mock_repo, mock_auth, client):
    """A single-entity ``.zip`` upload is read as a bundle: the route hands the
    entity's envelope + assets to ``attach_assets`` before ``import_``."""
    seen = {}

    class _ZipImportExchanger(EntityExchanger):
        entity_key = "pics"
        label = "Pics"
        cluster = "sales"
        natural_key = "slug"
        supports_export = False
        supports_import = True
        supported_formats = frozenset({"json", "zip"})
        secret_fields = frozenset()
        pii_fields = frozenset()

        def export(self, selector, *, include_pii):
            raise UnsupportedOperationError("pics is import-only")

        def attach_assets(self, envelope, assets):
            seen["assets"] = dict(assets)
            row = envelope["pics"][0]
            row["data"] = base64.b64encode(assets[row["asset_file"]]).decode("ascii")
            return envelope

        def import_(self, payload, *, mode, dry_run):
            seen["data"] = payload["pics"][0]["data"]
            return ImportResult(entity="pics", mode=mode, dry_run=dry_run, created=1)

    data_exchange_registry.register(_ZipImportExchanger())
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("pics.import"))

    from vbwd.services.data_exchange.envelope import BundleEntry, build_bundle

    bundle = build_bundle(
        [
            BundleEntry(
                "pics",
                "json",
                build_envelope(
                    "pics", [{"slug": "a", "asset_file": "a.png"}], instance="main"
                ),
            )
        ],
        instance="main",
        assets={"a.png": b"raw-bytes"},
    )
    response = client.post(
        "/api/v1/admin/data-exchange/pics/import",
        headers=_headers(),
        data={"file": (io.BytesIO(bundle), "pics.zip"), "mode": "upsert"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.get_json()["created"] == 1
    assert seen["assets"] == {"a.png": b"raw-bytes"}
    assert base64.b64decode(seen["data"]) == b"raw-bytes"


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
def test_bundle_export_includes_real_assets_for_zip_entities(
    mock_repo, mock_auth, client
):
    """The General-tab "everything" ZIP carries real binary files for
    zip-capable entities (it uses ``export_zip``, not the base64 ``export``)."""

    class _ZipBundleExchanger(EntityExchanger):
        entity_key = "pics"
        label = "Pics"
        cluster = "sales"
        natural_key = "slug"
        supports_export = True
        supports_import = False
        supported_formats = frozenset({"json", "zip"})
        secret_fields = frozenset()
        pii_fields = frozenset()

        def export(self, selector, *, include_pii):
            return Envelope(entity_key="pics", rows=[{"slug": "a", "data": "ZA=="}])

        def export_zip(self, selector, *, include_pii):
            from vbwd.services.data_exchange.port import ZipExport

            return ZipExport(
                rows=[{"slug": "a", "asset_file": "a.png"}],
                assets={"a.png": b"bundle-bytes"},
            )

        def import_(self, payload, *, mode, dry_run):
            raise UnsupportedOperationError("pics is export-only")

    data_exchange_registry.register(_ZipBundleExchanger())
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("pics.export"))
    response = client.post(
        "/api/v1/admin/data-exchange/export",
        headers=_headers(),
        json={"entities": ["pics"]},
    )
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.data))
    assert "assets/a.png" in archive.namelist()
    assert archive.read("assets/a.png") == b"bundle-bytes"


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


# ── S89: NDJSON streaming export/import + server-side stage timing ───────────


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_export_ndjson_streams_header_then_rows(mock_repo, mock_auth, client):
    _mock_auth(mock_repo, mock_auth, _superadmin())
    response = client.post(
        "/api/v1/admin/data-exchange/widgets/export",
        headers=_headers(),
        json={"all": True, "format": "ndjson"},
    )
    assert response.status_code == 200
    assert response.mimetype == "application/x-ndjson"
    lines = [line for line in response.get_data(as_text=True).splitlines() if line]
    header = json.loads(lines[0])
    assert header["vbwd_export"] == "widgets"
    assert header["format"] == "ndjson"
    rows = [json.loads(line) for line in lines[1:]]
    assert rows[0]["code"] == "a"


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_export_ndjson_mid_stream_error_is_not_silently_truncated(
    mock_repo, mock_auth, client
):
    """A mid-stream failure must NOT come back as a clean, short 200 body.

    Reproduces the S89 load-test finding: ``iter_export`` (a lazy ``yield_per``
    DB iterator driven under ``stream_with_context``) raised after emitting some
    rows, but the generator swallowed it, so the client got 200 OK with a
    truncated body and no signal that data was lost. The streaming generator
    must instead fail loudly — propagate the error out of the response so the
    transfer is aborted, never finish a clean partial download.
    """

    class _MidStreamFailExchanger(EntityExchanger):
        entity_key = "widgets"
        label = "Widgets"
        cluster = "sales"
        natural_key = "code"
        supports_export = True
        supports_import = False
        supported_formats = frozenset({"json", "ndjson"})
        secret_fields = frozenset()
        pii_fields = frozenset()

        def export(self, selector, *, include_pii):  # pragma: no cover - unused
            return Envelope(entity_key="widgets", rows=[])

        def iter_export(self, selector, *, chunk_size, include_pii):
            yield [{"code": "a"}, {"code": "b"}]
            raise RuntimeError("boom mid-stream (server-side cursor died)")

        def import_(self, payload, *, mode, dry_run):  # pragma: no cover - unused
            raise UnsupportedOperationError("export-only")

    data_exchange_registry.register(_MidStreamFailExchanger())
    _mock_auth(mock_repo, mock_auth, _superadmin())
    with pytest.raises(RuntimeError, match="boom mid-stream"):
        response = client.post(
            "/api/v1/admin/data-exchange/widgets/export",
            headers=_headers(),
            json={"all": True, "format": "ndjson"},
        )
        # Force the lazy stream to drain — the error must surface here, never as
        # a silently truncated 200 body.
        response.get_data()


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_import_ndjson_upload_streams_rows(mock_repo, mock_auth, client):
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("widgets.import"))
    ndjson = (
        json.dumps({"vbwd_export": "widgets", "version": 1, "format": "ndjson"})
        + "\n"
        + json.dumps({"code": "x", "label": "X"})
        + "\n"
        + json.dumps({"code": "y", "label": "Y"})
        + "\n"
    )
    response = client.post(
        "/api/v1/admin/data-exchange/widgets/import",
        headers=_headers(),
        data={
            "file": (io.BytesIO(ndjson.encode("utf-8")), "widgets.ndjson"),
            "mode": "upsert",
            "format": "ndjson",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["created"] == 2


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_import_no_profile_header_when_flag_off(
    mock_repo, mock_auth, client, monkeypatch
):
    monkeypatch.delenv("VBWD_DATA_EXCHANGE_PROFILE", raising=False)
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("widgets.import"))
    response = client.post(
        "/api/v1/admin/data-exchange/widgets/import",
        headers=_headers(),
        json={"payload": {"widgets": [{"code": "x"}]}, "mode": "upsert"},
    )
    assert response.status_code == 200
    assert "Server-Timing" not in response.headers
    assert "_profile" not in response.get_json()


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_import_emits_profile_when_flag_on(mock_repo, mock_auth, client, monkeypatch):
    monkeypatch.setenv("VBWD_DATA_EXCHANGE_PROFILE", "1")
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("widgets.import"))
    response = client.post(
        "/api/v1/admin/data-exchange/widgets/import",
        headers=_headers(),
        json={"payload": {"widgets": [{"code": "x"}]}, "mode": "upsert"},
    )
    assert response.status_code == 200
    assert "Server-Timing" in response.headers
    assert "_profile" in response.get_json()

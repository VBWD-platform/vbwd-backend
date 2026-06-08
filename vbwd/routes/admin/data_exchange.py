"""Generic admin data-exchange routes (S46.0 seam).

These routes name no entity — they resolve the exchanger from the registry by
``<key>`` and drive its generic contract. Per-entity export/import perms are
enforced here; ``replace_all`` is additionally superadmin-gated server-side.
"""
import io
import json

from flask import Blueprint, g, jsonify, request, send_file

from vbwd.middleware.auth import require_admin, require_auth
from vbwd.services.data_exchange.base_model_exchanger import RowCapExceededError
from vbwd.services.data_exchange.envelope import (
    BundleEntry,
    EnvelopeError,
    build_bundle,
    build_envelope,
    read_bundle,
    rows_to_csv,
    validate_envelope,
)
from vbwd.services.data_exchange.port import (
    MODE_REPLACE_ALL,
    ExportSelector,
    UnsupportedOperationError,
)
from vbwd.services.data_exchange.registry import (
    SUPERADMIN_ROLE,
    data_exchange_registry,
)

data_exchange_bp = Blueprint(
    "admin_data_exchange", __name__, url_prefix="/api/v1/admin/data-exchange"
)

CSV_FORMAT = "csv"
JSON_FORMAT = "json"
ZIP_FORMAT = "zip"
ROW_CAP_STATUS = 413
ZIP_MAGIC = b"PK\x03\x04"


def _instance_name() -> str:
    from flask import current_app

    return current_app.config.get("VBWD_INSTANCE", "default")


def _enabled_entities():
    from flask import current_app

    return current_app.config.get("DATA_EXCHANGE_ENABLED_ENTITIES")


def _is_superadmin() -> bool:
    role = getattr(g.user, "role", None)
    return getattr(role, "value", None) == SUPERADMIN_ROLE


def _selector_from_body(body: dict) -> ExportSelector:
    return ExportSelector(
        ids=body.get("ids"),
        filters=body.get("filters"),
        all=bool(body.get("all", False)),
    )


@data_exchange_bp.route("/manifest", methods=["GET"])
@require_auth
@require_admin
def get_manifest():
    """Return the clustered, perm/config-filtered manifest for the caller."""
    entities = data_exchange_registry.manifest_for(
        g.user, enabled_entities=_enabled_entities()
    )
    return jsonify({"entities": entities}), 200


@data_exchange_bp.route("/<key>/export", methods=["POST"])
@require_auth
@require_admin
def export_entity(key: str):
    """Export a single entity as a JSON or CSV download."""
    exchanger = data_exchange_registry.get(key)
    if exchanger is None:
        return jsonify({"error": f"unknown entity '{key}'"}), 404
    if not data_exchange_registry.can_export(exchanger, g.user):
        return jsonify({"error": "Permission denied"}), 403

    body = request.get_json(silent=True) or {}
    export_format = body.get("format", JSON_FORMAT)
    include_pii = data_exchange_registry.can_export_pii(exchanger, g.user)
    selector = _selector_from_body(body)

    if export_format == ZIP_FORMAT:
        if ZIP_FORMAT not in exchanger.supported_formats:
            return (
                jsonify({"error": f"entity '{key}' does not support zip export"}),
                400,
            )
        return _export_zip(exchanger, key, selector, include_pii=include_pii)

    try:
        rows = exchanger.export(selector, include_pii=include_pii).rows
    except UnsupportedOperationError as exc:
        return jsonify({"error": str(exc)}), 400
    except RowCapExceededError as exc:
        return jsonify({"error": str(exc)}), ROW_CAP_STATUS

    if export_format == CSV_FORMAT and CSV_FORMAT in exchanger.supported_formats:
        payload = rows_to_csv(rows).encode("utf-8")
        return send_file(
            io.BytesIO(payload),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"vbwd-{key}.csv",
        )
    envelope = build_envelope(key, rows, instance=_instance_name())
    response = jsonify(envelope)
    response.headers["Content-Disposition"] = f"attachment; filename=vbwd-{key}.json"
    return response, 200


def _export_zip(exchanger, key: str, selector, *, include_pii: bool):
    """Export one zip-capable entity as a real ZIP bundle (rows + binary assets).

    Reuses ``build_bundle`` (DRY): one JSON ``BundleEntry`` for the rows plus the
    exchanger's binary assets under ``assets/``. The fe saves this as
    ``vbwd-<key>.zip`` and it is a genuine archive (the original bug saved a JSON
    envelope under a ``.zip`` name).
    """
    try:
        zip_export = exchanger.export_zip(selector, include_pii=include_pii)
    except UnsupportedOperationError as exc:
        return jsonify({"error": str(exc)}), 400
    except RowCapExceededError as exc:
        return jsonify({"error": str(exc)}), ROW_CAP_STATUS

    envelope = build_envelope(key, zip_export.rows, instance=_instance_name())
    entry = BundleEntry(entity_key=key, export_format=JSON_FORMAT, content=envelope)
    archive = build_bundle([entry], instance=_instance_name(), assets=zip_export.assets)
    return send_file(
        io.BytesIO(archive),
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"vbwd-{key}.zip",
    )


@data_exchange_bp.route("/<key>/import", methods=["POST"])
@require_auth
@require_admin
def import_entity(key: str):
    """Import a single entity (JSON body or multipart file)."""
    exchanger = data_exchange_registry.get(key)
    if exchanger is None:
        return jsonify({"error": f"unknown entity '{key}'"}), 404
    if not data_exchange_registry.can_import(exchanger, g.user):
        return jsonify({"error": "Permission denied"}), 403

    payload, assets, mode, dry_run, error = _read_import_request(key, exchanger)
    if error is not None:
        return jsonify({"error": error}), 400

    if mode == MODE_REPLACE_ALL and not _is_superadmin():
        return jsonify({"error": "replace_all requires superadmin"}), 403

    if assets:
        payload = exchanger.attach_assets(payload, assets)

    try:
        result = exchanger.import_(payload, mode=mode, dry_run=dry_run)
    except UnsupportedOperationError as exc:
        return jsonify({"error": str(exc)}), 400
    except EnvelopeError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result.to_dict()), 200


def _read_import_request(key: str, exchanger):
    """Return (payload, assets, mode, dry_run, error) from JSON, file, or zip.

    A multipart upload may be a JSON envelope or a ZIP bundle (single-entity
    export with binary ``assets/``). A zip is detected by its magic bytes so the
    fe need not set a special content type; the json/csv import path is unchanged.
    """
    if request.files:
        uploaded = request.files.get("file")
        mode = request.form.get("mode", "upsert")
        dry_run = request.form.get("dry_run", "false").lower() == "true"
        if uploaded is None:
            return None, None, mode, dry_run, "no file uploaded"
        raw = uploaded.read()
        if raw.startswith(ZIP_MAGIC):
            return _read_zip_import(key, raw, mode, dry_run)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            return None, None, mode, dry_run, f"invalid JSON file: {exc}"
        return data, None, mode, dry_run, None

    body = request.get_json(silent=True)
    if body is None:
        return None, None, "upsert", False, "request body must be JSON"
    payload = body.get("payload", body)
    mode = body.get("mode", "upsert")
    dry_run = bool(body.get("dry_run", False))
    return payload, None, mode, dry_run, None


def _read_zip_import(key: str, raw: bytes, mode: str, dry_run: bool):
    """Read a single-entity zip upload → (envelope, assets, mode, dry_run, err)."""
    try:
        _manifest, entries, assets = read_bundle(raw)
    except EnvelopeError as exc:
        return None, None, mode, dry_run, str(exc)
    envelope = entries.get(key)
    if envelope is None:
        return None, None, mode, dry_run, f"bundle has no '{key}' entity"
    return envelope, assets, mode, dry_run, None


@data_exchange_bp.route("/export", methods=["POST"])
@require_auth
@require_admin
def export_bundle():
    """Export several entities as a ZIP bundle; drops un-permitted entities."""
    body = request.get_json(silent=True) or {}
    requested = body.get("entities", [])
    export_format = body.get("format", JSON_FORMAT)
    if not isinstance(requested, list):
        return jsonify({"error": "'entities' must be a list"}), 400

    entries = []
    assets: dict = {}
    dropped = []
    for entity_key in requested:
        exchanger = data_exchange_registry.get(entity_key)
        if exchanger is None or not data_exchange_registry.can_export(
            exchanger, g.user
        ):
            dropped.append(entity_key)
            continue
        include_pii = data_exchange_registry.can_export_pii(exchanger, g.user)
        entry = _bundle_entry_for(
            exchanger, entity_key, export_format, include_pii, assets
        )
        if entry is None:
            # Per-entity failure is reported via the dropped header, not fatal.
            dropped.append(entity_key)
            continue
        entries.append(entry)

    archive = build_bundle(entries, instance=_instance_name(), assets=assets)
    response = send_file(
        io.BytesIO(archive),
        mimetype="application/zip",
        as_attachment=True,
        download_name="vbwd-data-exchange.zip",
    )
    response.headers["X-Dropped-Entities"] = ",".join(dropped)
    return response


def _bundle_entry_for(exchanger, entity_key, export_format, include_pii, assets):
    """Build one entity's BundleEntry, accumulating any binary assets.

    CSV is unchanged. A zip-capable entity uses ``export_zip`` so the bundle
    contains its real binaries (the asset filenames stay as the row's
    ``asset_file`` references — for cms_images that already includes the unique
    slug); every other entity uses the base64 ``export``. Returns ``None`` on a
    per-entity export failure (the caller drops it).
    """
    use_csv = export_format == CSV_FORMAT and CSV_FORMAT in exchanger.supported_formats
    try:
        if not use_csv and ZIP_FORMAT in exchanger.supported_formats:
            zip_export = exchanger.export_zip(
                ExportSelector(all=True), include_pii=include_pii
            )
            assets.update(zip_export.assets)
            return BundleEntry(
                entity_key=entity_key,
                export_format=JSON_FORMAT,
                content=build_envelope(
                    entity_key, zip_export.rows, instance=_instance_name()
                ),
            )
        envelope = exchanger.export(ExportSelector(all=True), include_pii=include_pii)
    except (RowCapExceededError, UnsupportedOperationError):
        return None
    content = (
        rows_to_csv(envelope.rows)
        if use_csv
        else build_envelope(entity_key, envelope.rows, instance=_instance_name())
    )
    return BundleEntry(
        entity_key=entity_key,
        export_format=CSV_FORMAT if use_csv else JSON_FORMAT,
        content=content,
    )


@data_exchange_bp.route("/import", methods=["POST"])
@require_auth
@require_admin
def import_bundle():
    """Import a multipart ZIP bundle → per-entity ImportResult list (D6)."""
    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify({"error": "no file uploaded"}), 400
    mode = request.form.get("mode", "upsert")
    dry_run = request.form.get("dry_run", "false").lower() == "true"

    if mode == MODE_REPLACE_ALL and not _is_superadmin():
        return jsonify({"error": "replace_all requires superadmin"}), 403

    try:
        _manifest, entries, _assets = read_bundle(uploaded.read())
    except EnvelopeError as exc:
        return jsonify({"error": str(exc)}), 400

    results = []
    for entity_key, envelope in entries.items():
        exchanger = data_exchange_registry.get(entity_key)
        if exchanger is None or not data_exchange_registry.can_import(
            exchanger, g.user
        ):
            results.append(
                {
                    "entity": entity_key,
                    "mode": mode,
                    "dry_run": dry_run,
                    "created": 0,
                    "updated": 0,
                    "skipped": 0,
                    "errors": [{"row": -1, "reason": "not permitted or unknown"}],
                }
            )
            continue
        try:
            validate_envelope(envelope, entity_key)
            result = exchanger.import_(envelope, mode=mode, dry_run=dry_run)
            results.append(result.to_dict())
        except (UnsupportedOperationError, EnvelopeError) as exc:
            results.append(
                {
                    "entity": entity_key,
                    "mode": mode,
                    "dry_run": dry_run,
                    "created": 0,
                    "updated": 0,
                    "skipped": 0,
                    "errors": [{"row": -1, "reason": str(exc)}],
                }
            )
    return jsonify({"results": results}), 200

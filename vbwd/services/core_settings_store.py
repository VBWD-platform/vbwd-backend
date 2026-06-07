"""File-backed store for the core (provider / contact / address / bank) settings.

Generic core infrastructure — names no plugin domain. The settings are
persisted as a single JSON file at ``${VBWD_VAR_DIR:-/app/var}/core/vbwd_settings.json``.
The ``var/`` directory is already host-mounted into the backend, so the file
survives restarts/redeploys and is the single source of truth shared by every
gunicorn worker (in-memory state was per-worker and wiped on restart).

``DEFAULT_CORE_SETTINGS`` is the single source of truth for the schema: missing
or newly-added keys are filled from it on read, and only known keys are accepted
on write. Reads never raise — a missing or corrupt file degrades to defaults.
"""
import json
import logging
import os
import tempfile
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Single source of truth for the core-settings schema. Adding a key here makes
# it appear (with its default) for every existing deployment on the next read.
DEFAULT_CORE_SETTINGS: Dict[str, Any] = {
    "provider_name": "",
    "contact_email": "",
    "website_url": "",
    "other_links": "",
    "address_street": "",
    "address_city": "",
    "address_postal_code": "",
    "address_country": "",
    "bank_name": "",
    "bank_iban": "",
    "bank_bic": "",
}

_DEFAULT_VAR_DIR = "/app/var"


def _path() -> str:
    """Absolute path to the persisted settings file."""
    var_dir = os.environ.get("VBWD_VAR_DIR", _DEFAULT_VAR_DIR)
    return os.path.join(var_dir, "core", "vbwd_settings.json")


def get_core_settings() -> Dict[str, Any]:
    """Return the persisted settings merged over the defaults.

    Defaults fill any missing or newly-added keys. A missing or corrupt file
    degrades to defaults (logged) and never raises.
    """
    path = _path()
    file_values: Dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                file_values = loaded
            else:
                logger.warning(
                    "Core settings file %s is not a JSON object; using defaults.",
                    path,
                )
        except (json.JSONDecodeError, OSError) as error:
            logger.warning(
                "Could not read core settings file %s (%s); using defaults.",
                path,
                error,
            )
    return {**DEFAULT_CORE_SETTINGS, **file_values}


def update_core_settings(partial: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``partial`` (known keys only) into the stored settings and persist.

    Unknown keys are ignored. The write is atomic (temp file in the same
    directory + ``os.replace``) so a concurrent read never sees a half-written
    file. Last-writer-wins; settings edits are rare and serial, so no lock.

    Returns the merged settings.
    """
    current = get_core_settings()
    current.update({k: v for k, v in partial.items() if k in DEFAULT_CORE_SETTINGS})

    path = _path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)

    file_descriptor, temp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(current, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    except OSError:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise

    return current

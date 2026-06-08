"""File-backed store for the core (provider / contact / address / bank) settings.

Generic core infrastructure — names no plugin domain. The settings are
persisted as a single JSON file at ``${VBWD_VAR_DIR:-/app/var}/core/vbwd_settings.json``.
The ``var/`` directory is already host-mounted into the backend, so the file
survives restarts/redeploys and is the single source of truth shared by every
gunicorn worker (in-memory state was per-worker and wiped on restart).

``DEFAULT_CORE_SETTINGS`` is the single source of truth for the schema: missing
or newly-added keys are filled from it on read, and only known keys are accepted
on write. Reads never raise — a missing or corrupt file degrades to defaults.

Sprint 58.1: the actual file IO now flows through the unified
``FilesystemManager`` (the ``core`` namespace = ATOMIC_REPLACE), instead of the
hand-rolled ``mkstemp`` + ``os.replace``. The on-disk path, the default /
corruption-tolerance behaviour, and the public API are all unchanged; the write
is still atomic and crash-safe, just centralised behind one audited seam.
"""
import logging
from typing import Any, Dict

from vbwd.services.filesystem import LocalFilesystemManager

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

# The core namespace stores ``${VBWD_VAR_DIR}/core/vbwd_settings.json`` — the
# exact path the hand-rolled writer used.
_CORE_NAMESPACE = "core"
_SETTINGS_FILE = "vbwd_settings.json"


def _manager() -> LocalFilesystemManager:
    """Return a FilesystemManager bound to the current ``VBWD_VAR_DIR``.

    Built per call (cheaply) so that an env change between requests — and the
    test harness's per-test ``monkeypatch.setenv("VBWD_VAR_DIR", ...)`` — is
    honoured, matching the previous module-level ``os.environ.get`` behaviour.
    """
    return LocalFilesystemManager()


def get_core_settings() -> Dict[str, Any]:
    """Return the persisted settings merged over the defaults.

    Defaults fill any missing or newly-added keys. A missing or corrupt file
    degrades to defaults (logged) and never raises.
    """
    loaded = _manager().read_json(_CORE_NAMESPACE, _SETTINGS_FILE, default=None)
    file_values: Dict[str, Any] = {}
    if isinstance(loaded, dict):
        file_values = loaded
    elif loaded is not None:
        logger.warning(
            "Core settings file %s/%s is not a JSON object; using defaults.",
            _CORE_NAMESPACE,
            _SETTINGS_FILE,
        )
    return {**DEFAULT_CORE_SETTINGS, **file_values}


def update_core_settings(partial: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``partial`` (known keys only) into the stored settings and persist.

    Unknown keys are ignored. The write is atomic (temp file in the same
    directory + ``os.replace``, via the manager's ``core`` namespace) so a
    concurrent read never sees a half-written file. Last-writer-wins; settings
    edits are rare and serial, so no lock.

    Returns the merged settings.
    """
    current = get_core_settings()
    current.update({k: v for k, v in partial.items() if k in DEFAULT_CORE_SETTINGS})
    _manager().write_json(_CORE_NAMESPACE, _SETTINGS_FILE, current)
    return current

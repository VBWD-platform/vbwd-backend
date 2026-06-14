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
from typing import Any, Callable, Dict, Optional, Set

from vbwd.services.filesystem import LocalFilesystemManager

logger = logging.getLogger(__name__)

# S72.4: the global netto/brutto price-display toggle. ``brutto`` (gross,
# tax-included) is the default; ``netto`` shows net (tax-excluded) prices.
PRICES_DISPLAY_MODES = ("brutto", "netto")

# S85.0: how the stored ``price`` double is *interpreted* (orthogonal to the
# display toggle above). ``NETTO`` (default) = the stored number is the net
# amount; ``BRUTTO`` = the stored number already includes tax.
PRICES_MODE_IN_DB_KEY = "prices_mode_in_db"
PRICES_DB_MODES = ("NETTO", "BRUTTO")

# S84: cross-rate base — rates are presented either against the default
# currency or against USD (a view transform crossed via the default).
CROSS_RATE_BASES = ("default", "usd")

# An ISO 4217 code is three ASCII letters.
_ISO_CODE_LENGTH = 3

# S84: pluggable currency-catalog provider. Returns the set of catalog codes
# (uppercase) so the currency validators can enforce membership WITHOUT this
# infrastructure module importing the DB/model layer (no import cycle). The
# app wires a DB-backed provider at startup; left ``None`` (tests / cold
# boot) the validators fall back to structural-only checks.
_currency_catalog_provider: Optional[Callable[[], Set[str]]] = None


def register_currency_catalog_provider(
    provider: Optional[Callable[[], Set[str]]],
) -> None:
    """Register (or clear with ``None``) the currency-catalog code provider.

    Called once at app startup with a DB-backed callable. Keeping the wiring
    here — instead of importing the repository — keeps this generic settings
    module free of a settings→DB import cycle (Dependency Inversion).
    """
    global _currency_catalog_provider
    _currency_catalog_provider = provider


def _catalog_codes() -> Optional[Set[str]]:
    """Return the catalog code set, or ``None`` when no provider is wired."""
    if _currency_catalog_provider is None:
        return None
    return _currency_catalog_provider()


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
    "prices_display_mode": "brutto",
    # S85.0: prices are stored net by default (D7).
    PRICES_MODE_IN_DB_KEY: "NETTO",
    # S84: active set + default + cross-rate base are the single source of
    # truth for currency selection (the ``vbwd_currency`` table is catalog +
    # rates only). The default must always be a member of the active set.
    "default_currency": "EUR",
    "active_currencies": ["EUR"],
    "cross_rate_base": "default",
}

# Per-key value validators. A key absent from this map accepts any value (the
# free-form string settings). A validator raises ``ValueError`` to reject an
# out-of-enum value, which aborts the whole update (nothing is persisted).
_KEY_VALIDATORS: Dict[str, Callable[[Any], None]] = {}


def _validate_prices_display_mode(value: Any) -> None:
    if value not in PRICES_DISPLAY_MODES:
        raise ValueError(
            "prices_display_mode must be one of "
            f"{PRICES_DISPLAY_MODES}, got {value!r}"
        )


_KEY_VALIDATORS["prices_display_mode"] = _validate_prices_display_mode


def _validate_prices_mode_in_db(value: Any) -> None:
    if value not in PRICES_DB_MODES:
        raise ValueError(
            "prices_mode_in_db must be one of " f"{PRICES_DB_MODES}, got {value!r}"
        )


_KEY_VALIDATORS[PRICES_MODE_IN_DB_KEY] = _validate_prices_mode_in_db


def _is_iso_code(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _ISO_CODE_LENGTH
        and value.isalpha()
        and value == value.upper()
    )


def _validate_cross_rate_base(value: Any) -> None:
    if value not in CROSS_RATE_BASES:
        raise ValueError(
            f"cross_rate_base must be one of {CROSS_RATE_BASES}, got {value!r}"
        )


def _validate_default_currency(value: Any) -> None:
    if not _is_iso_code(value):
        raise ValueError(
            f"default_currency must be an uppercase ISO-3 code, got {value!r}"
        )
    catalog = _catalog_codes()
    if catalog is not None and value not in catalog:
        raise ValueError(f"default_currency {value!r} is not in the currency catalog")


def _validate_active_currencies(value: Any) -> None:
    if not isinstance(value, list) or not all(_is_iso_code(item) for item in value):
        raise ValueError(
            "active_currencies must be a list of uppercase ISO-3 codes, "
            f"got {value!r}"
        )
    catalog = _catalog_codes()
    if catalog is not None:
        unknown = [code for code in value if code not in catalog]
        if unknown:
            raise ValueError(
                f"active_currencies contains codes not in the catalog: {unknown}"
            )


_KEY_VALIDATORS["cross_rate_base"] = _validate_cross_rate_base
_KEY_VALIDATORS["default_currency"] = _validate_default_currency
_KEY_VALIDATORS["active_currencies"] = _validate_active_currencies


def _validate_default_is_active(merged: Dict[str, Any]) -> None:
    """Cross-key rule: the default currency must be in the active set.

    Evaluated against the *resulting* settings (the partial merged over the
    current stored values), so an update that changes either key in a way
    that would leave the default inactive is rejected as a whole.
    """
    default_code = merged.get("default_currency")
    active = merged.get("active_currencies", [])
    if default_code not in active:
        raise ValueError(
            f"default_currency {default_code!r} must be a member of "
            f"active_currencies {active!r}"
        )


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

    Unknown keys are ignored. Known keys with a registered validator are
    checked first; an invalid value raises ``ValueError`` and aborts the whole
    update (nothing is persisted). The write is atomic (temp file in the same
    directory + ``os.replace``, via the manager's ``core`` namespace) so a
    concurrent read never sees a half-written file. Last-writer-wins; settings
    edits are rare and serial, so no lock.

    Returns the merged settings.

    Raises:
        ValueError: when a known key's value fails its validator.
    """
    known = {k: v for k, v in partial.items() if k in DEFAULT_CORE_SETTINGS}
    for key, value in known.items():
        validator = _KEY_VALIDATORS.get(key)
        if validator is not None:
            validator(value)
    current = get_core_settings()
    current.update(known)
    # Cross-key rule, checked on the resulting state so neither key can be
    # changed into an inconsistent combination (default must stay active).
    _validate_default_is_active(current)
    _manager().write_json(_CORE_NAMESPACE, _SETTINGS_FILE, current)
    return current

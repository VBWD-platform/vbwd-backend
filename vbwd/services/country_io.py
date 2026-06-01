"""Manual export / import of the country catalog (VBWD standard JSON).

Two operator actions backing the Settings → Countries tab buttons:

* :func:`export_countries` — serialise the whole catalog into a portable,
  instance-independent envelope (no ids / timestamps), ready to download.
* :func:`import_countries` — upsert a previously exported envelope back in,
  keyed by ``code`` (create missing, update name / is_enabled / position).

The envelope is the VBWD standard shape so the same format round-trips and can
be hand-edited::

    {"vbwd_export": "countries", "version": 1, "countries": [
        {"code": "DE", "name": "Germany", "is_enabled": true, "position": 0}
    ]}
"""
from dataclasses import dataclass
from uuid import uuid4

from vbwd.models.country import Country
from vbwd.repositories.country_repository import CountryRepository

EXPORT_KIND = "countries"
EXPORT_VERSION = 1

# Disabled rows get this sentinel position (mirrors disable_country).
DISABLED_POSITION = 999


class CountryImportError(ValueError):
    """Raised when an import payload is not a valid country envelope."""


@dataclass(frozen=True)
class CountryImportResult:
    """Counts from an import run."""

    created: int = 0
    updated: int = 0


def export_countries(session) -> dict:
    """Return the full catalog as a portable VBWD-standard envelope.

    Countries are ordered (enabled first by position, then the rest) and
    stripped of instance-specific fields (id / timestamps) so the file can be
    imported into any instance.
    """
    repo = CountryRepository(session)
    countries = repo.find_all_ordered()
    return {
        "vbwd_export": EXPORT_KIND,
        "version": EXPORT_VERSION,
        "countries": [
            {
                "code": country.code,
                "name": country.name,
                "is_enabled": bool(country.is_enabled),
                "position": int(country.position),
            }
            for country in countries
        ],
    }


def import_countries(session, payload: dict) -> CountryImportResult:
    """Upsert a country envelope by ``code``.

    Existing countries are updated (name / is_enabled / position); unknown
    codes are created. Idempotent: re-importing the same export changes
    nothing. Raises :class:`CountryImportError` on a malformed envelope.
    """
    if not isinstance(payload, dict):
        raise CountryImportError("payload must be a JSON object")

    kind = payload.get("vbwd_export")
    if kind is not None and kind != EXPORT_KIND:
        raise CountryImportError(
            f"unexpected export kind '{kind}', expected '{EXPORT_KIND}'"
        )

    rows = payload.get("countries")
    if not isinstance(rows, list):
        raise CountryImportError("'countries' must be a list")

    repo = CountryRepository(session)
    created = 0
    updated = 0

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CountryImportError(f"countries[{index}] must be an object")

        code = row.get("code")
        name = row.get("name")
        if not isinstance(code, str) or not code.strip():
            raise CountryImportError(f"countries[{index}] missing 'code'")
        if not isinstance(name, str) or not name.strip():
            raise CountryImportError(f"countries[{index}] missing 'name'")

        is_enabled = bool(row.get("is_enabled", False))
        position = row.get("position")
        if not isinstance(position, int):
            position = 0 if is_enabled else DISABLED_POSITION

        existing = repo.find_by_code(code)
        if existing:
            # Column-keyed UPDATE (not attribute assignment) so the values are
            # type-checked against plain str/bool/int, not Column[...].
            session.query(Country).filter(Country.code == code).update(
                {
                    Country.name: name,
                    Country.is_enabled: is_enabled,
                    Country.position: position,
                }
            )
            updated += 1
        else:
            session.add(
                Country(
                    id=uuid4(),
                    code=code,
                    name=name,
                    is_enabled=is_enabled,
                    position=position,
                )
            )
            created += 1

    session.commit()
    return CountryImportResult(created=created, updated=updated)

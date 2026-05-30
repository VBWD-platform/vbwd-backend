"""Core country seeder — Sprint S39 §8b.

Idempotently seeds the foundational billing-address country reference data
(shown at ``/admin/settings``) into ``vbwd_country``. Ungated — countries
are default reference data on every instance, prod included, just like the
RBAC default roles. Safe to re-run on every deploy after ``flask db upgrade``;
a second run creates nothing new (upsert by ISO code, existing rows untouched).

This module is the single source of truth for the default country list and
which codes ship enabled — the gated demo script delegates here (DRY).
"""
from dataclasses import dataclass
from uuid import uuid4

from vbwd.models.country import Country


# Codes enabled by default. DACH (DE, AT, CH) MUST be enabled —
# tests/integration/test_admin_countries.py::test_list_includes_dach_enabled
# asserts it.
ENABLED_CODES = {"DE", "AT", "CH", "FR", "IT", "PL", "ES", "TH"}

# Default country catalog as (ISO 3166-1 alpha-2 code, display name).
COUNTRIES = [
    ("AT", "Austria"),
    ("BE", "Belgium"),
    ("BG", "Bulgaria"),
    ("HR", "Croatia"),
    ("CY", "Cyprus"),
    ("CZ", "Czechia"),
    ("DK", "Denmark"),
    ("EE", "Estonia"),
    ("FI", "Finland"),
    ("FR", "France"),
    ("DE", "Germany"),
    ("GR", "Greece"),
    ("HU", "Hungary"),
    ("IE", "Ireland"),
    ("IT", "Italy"),
    ("LV", "Latvia"),
    ("LT", "Lithuania"),
    ("LU", "Luxembourg"),
    ("MT", "Malta"),
    ("NL", "Netherlands"),
    ("PL", "Poland"),
    ("PT", "Portugal"),
    ("RO", "Romania"),
    ("SK", "Slovakia"),
    ("SI", "Slovenia"),
    ("ES", "Spain"),
    ("SE", "Sweden"),
    ("CH", "Switzerland"),
    ("GB", "United Kingdom"),
    ("NO", "Norway"),
    ("IS", "Iceland"),
    ("LI", "Liechtenstein"),
    ("US", "United States"),
    ("CA", "Canada"),
    ("MX", "Mexico"),
    ("BR", "Brazil"),
    ("AR", "Argentina"),
    ("CL", "Chile"),
    ("CO", "Colombia"),
    ("AU", "Australia"),
    ("NZ", "New Zealand"),
    ("JP", "Japan"),
    ("KR", "South Korea"),
    ("CN", "China"),
    ("TW", "Taiwan"),
    ("SG", "Singapore"),
    ("TH", "Thailand"),
    ("IN", "India"),
    ("ID", "Indonesia"),
    ("MY", "Malaysia"),
    ("PH", "Philippines"),
    ("VN", "Vietnam"),
    ("IL", "Israel"),
    ("AE", "United Arab Emirates"),
    ("SA", "Saudi Arabia"),
    ("TR", "Turkey"),
    ("ZA", "South Africa"),
    ("NG", "Nigeria"),
    ("KE", "Kenya"),
    ("EG", "Egypt"),
    ("MA", "Morocco"),
    ("UA", "Ukraine"),
    ("RS", "Serbia"),
    ("BA", "Bosnia"),
    ("ME", "Montenegro"),
    ("MK", "North Macedonia"),
    ("AL", "Albania"),
    ("RU", "Russia"),
    ("BY", "Belarus"),
    ("MD", "Moldova"),
    ("GE", "Georgia"),
]

# Position assigned to disabled countries (sort to the end of the list).
DISABLED_POSITION = 999


@dataclass(frozen=True)
class CountrySeedResult:
    """Counts from a seeder run (idempotent re-runs report created=0)."""

    created: int = 0
    enabled_count: int = 0


def seed_countries(session) -> CountrySeedResult:
    """Idempotently upsert the default country catalog.

    For each ``(code, name)`` in :data:`COUNTRIES`, create a :class:`Country`
    if none exists for that code. Enabled countries (:data:`ENABLED_CODES`)
    get an ascending ``position``; disabled ones get :data:`DISABLED_POSITION`.
    Existing rows are left untouched, so an operator's enable/disable edits
    survive a re-run.

    Safe to re-run; a second run creates nothing new.
    """
    created = 0
    enabled_count = 0
    next_enabled_position = 0
    for code, name in COUNTRIES:
        existing = session.query(Country).filter_by(code=code).first()
        if existing:
            continue

        is_enabled = code in ENABLED_CODES
        session.add(
            Country(
                id=uuid4(),
                code=code,
                name=name,
                is_enabled=is_enabled,
                position=next_enabled_position if is_enabled else DISABLED_POSITION,
            )
        )
        created += 1
        if is_enabled:
            next_enabled_position += 1
            enabled_count += 1

    session.commit()

    return CountrySeedResult(created=created, enabled_count=enabled_count)

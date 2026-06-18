"""S99.5 — regression oracle: no hard-coded currency *fallback* literals in core.

The S99 contract: there is ONE billing currency, the ``default_currency`` core
setting (resolved via :func:`vbwd.services.core_settings_store.get_default_currency`).
Runtime code must resolve currency from the value's own currency or that setting
— never from a hard-coded ``"USD"`` / ``"EUR"`` fallback (the historical USD/EUR
split that rendered the SAME price with different symbols, and that could bill or
display the wrong currency).

This oracle walks the core ``vbwd/`` package and bans the three *fallback /
assignment* shapes that constituted the offenders, so a regression fails CI
without a running app:

* ``... or "USD"``                         (a literal fallback)
* ``currency="EUR"``                        (a literal kwarg/assignment)
* ``.get("currency", "USD")``               (a literal request-default)

It deliberately does NOT ban every currency literal — construction *defaults*
are an allowed home per the contract and do NOT match these patterns:
  - a typed default ``currency: str = "EUR"``  (has ``: str =``, not ``=``)
  - a column default ``default="EUR"``         (kwarg is ``default``, not ``currency``)
  - the setting default in ``core_settings_store`` / seed / docstrings.

Scope is core only (``vbwd/``); per-plugin repos carry their own equivalent
guard (and CI runs them in isolation, so a core test must not depend on a
plugin being cloned). Tests and Alembic migrations are excluded.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

# ISO codes that have appeared as literals in this codebase. Extend if a new
# operating currency is ever hard-coded — the point is to catch the fallback,
# not to enumerate ISO 4217.
_CURRENCY_CODES = r"USD|EUR|GBP|RUB|THB|MXN|KRW|JPY|CHF"

# The three offender shapes (see module docstring). Each is anchored so that
# typed defaults (``: str = "EUR"``), column defaults (``default="EUR"``), and
# docstring prose do not match.
_OFFENDER_PATTERNS = [
    re.compile(rf"""\bor\s+["']({_CURRENCY_CODES})["']"""),
    re.compile(rf"""(?<![:\w])currency\s*=\s*["']({_CURRENCY_CODES})["']"""),
    re.compile(rf"""\.get\(\s*["']currency["']\s*,\s*["']({_CURRENCY_CODES})["']"""),
]

_CORE_ROOT = Path(__file__).resolve().parents[2] / "vbwd"


def _python_files() -> List[Path]:
    return [
        path
        for path in _CORE_ROOT.rglob("*.py")
        if "migrations" not in path.parts and "__pycache__" not in path.parts
    ]


def _offences() -> List[Tuple[str, int, str]]:
    offences: List[Tuple[str, int, str]] = []
    for path in _python_files():
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.lstrip()
            # Skip full-line comments (docstring prose is filtered by the
            # anchored patterns, which only match code shapes).
            if stripped.startswith("#"):
                continue
            for pattern in _OFFENDER_PATTERNS:
                if pattern.search(line):
                    offences.append(
                        (
                            str(path.relative_to(_CORE_ROOT.parent)),
                            line_number,
                            line.strip(),
                        )
                    )
                    break
    return offences


def test_core_runtime_has_no_hardcoded_currency_fallbacks() -> None:
    offences = _offences()
    assert offences == [], (
        "Hard-coded currency fallback literal(s) found in core runtime — resolve "
        "from the value's own currency or get_default_currency() instead:\n"
        + "\n".join(f"  {f}:{n}  {text}" for f, n, text in offences)
    )


def test_oracle_detects_a_planted_fallback() -> None:
    """The oracle must actually fire — guard against a no-op regex (TDD self-check)."""
    planted = 'price_currency = invoice.currency or "USD"'
    assert any(pattern.search(planted) for pattern in _OFFENDER_PATTERNS)
    # And it must NOT flag the allowed construction-default shapes.
    for allowed in (
        'currency: str = "EUR"',
        'currency = db.Column(db.String(3), nullable=False, default="EUR")',
    ):
        assert not any(pattern.search(allowed) for pattern in _OFFENDER_PATTERNS)

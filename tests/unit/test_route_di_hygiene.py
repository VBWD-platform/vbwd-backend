"""S08 oracle — core routes must resolve services/repos via the container,
not construct them inline with ``db.session``.

Inline ``UserRepository(db.session)`` / ``AuthService(...)`` in route
bodies makes service swapping (for tests, for dependency-swap scenarios)
impossible and ignores the DI factories already wired in
``vbwd/container.py``. A regression of this kind also bypasses any
extension or override done via plugins.

Core admin routes are out of scope today (covered by [[s23]] when those
oversized handlers move into services).
"""
import os
import re


CORE_ROUTE_FILES = [
    "vbwd/routes/auth.py",
    "vbwd/routes/user.py",
    "vbwd/routes/invoices.py",
]


def _backend_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def test_core_routes_do_not_construct_repos_inline():
    """Any ``XxxRepository(db.session)`` call in a core route body is a
    regression — the container provides factories; use them."""
    pattern = re.compile(
        r"\b[A-Z][A-Za-z0-9_]*Repository\s*\(\s*db\.session\s*\)",
    )
    findings: list[str] = []
    for relative in CORE_ROUTE_FILES:
        absolute = os.path.join(_backend_root(), relative)
        with open(absolute) as handle:
            for line_number, line in enumerate(handle, start=1):
                if pattern.search(line):
                    findings.append(f"{relative}:{line_number} — {line.strip()}")
    assert not findings, (
        "Core routes must pull repositories from `current_app.container`, "
        f"not construct them inline. Found {len(findings)} site(s):\n  - "
        + "\n  - ".join(findings)
    )


def test_core_routes_do_not_construct_services_inline():
    """Same rule for services: ``AuthService(user_repository=...)`` etc."""
    pattern = re.compile(
        r"\b[A-Z][A-Za-z0-9_]*Service\s*\([^)]*user_repository\s*=",
    )
    findings: list[str] = []
    for relative in CORE_ROUTE_FILES:
        absolute = os.path.join(_backend_root(), relative)
        with open(absolute) as handle:
            for line_number, line in enumerate(handle, start=1):
                if pattern.search(line):
                    findings.append(f"{relative}:{line_number} — {line.strip()}")
    assert not findings, (
        "Core routes must pull services from `current_app.container`, "
        f"not construct them inline. Found {len(findings)} site(s):\n  - "
        + "\n  - ".join(findings)
    )

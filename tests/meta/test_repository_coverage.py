"""S16 meta-oracle — every core repository must ship a unit test file.

Discovery: walks ``vbwd/repositories/``, computes the expected test
filename, asserts it exists under ``tests/unit/repositories/``. The
oracle is intentionally a single test that fails with the full
backlog — when it lights up red, the message names every missing file.

The PRESENT backlog (as of 2026-05-27) is enumerated in
``EXPECTED_GAPS`` below. Each entry is removed from the gap list as the
matching test file is written (one slice per PR). When the last entry
is removed and a new repo is added without its test, the oracle goes
red and the next slice is created.

Note: this test does NOT enforce test quality (test count, coverage %)
— that's a follow-up oracle once the basic gap is closed.
"""
import os


# Track the historical S16 backlog so the oracle stays informative: as
# each test file is written, prune the corresponding entry. (A simple
# stricter test "every repo has a test file" lights up the entire list
# in one go and gives no signal about progress.)
EXPECTED_GAPS: set[str] = set()
# All 15 core repositories now have unit tests (S16 sweep completed
# 2026-05-27). Future new repos must ship with their test file or this
# meta oracle goes red.


def _backend_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def _repo_modules() -> set[str]:
    """Repository module names without the ``.py`` suffix, excluding
    ``__init__`` and ``base``."""
    repo_dir = os.path.join(_backend_root(), "vbwd", "repositories")
    names: set[str] = set()
    for filename in os.listdir(repo_dir):
        if not filename.endswith(".py"):
            continue
        stem = filename[:-3]
        if stem in {"__init__", "base"}:
            continue
        names.add(stem)
    return names


def _existing_repo_tests() -> set[str]:
    test_dir = os.path.join(_backend_root(), "tests", "unit", "repositories")
    if not os.path.isdir(test_dir):
        return set()
    out: set[str] = set()
    for filename in os.listdir(test_dir):
        if filename.startswith("test_") and filename.endswith(".py"):
            out.add(filename[len("test_") : -3])
    return out


def test_repository_test_coverage_progress():
    """Tracks the S16 backlog: the actual gap must match ``EXPECTED_GAPS``.

    If the actual gap is LARGER (a new repo added without its test) — fail
    with the new addition.  If SMALLER (a new test added) — fail with a
    hint to prune ``EXPECTED_GAPS``.
    """
    repos = _repo_modules()
    tested = _existing_repo_tests()
    actual_gap = repos - tested
    unexpected_new = actual_gap - EXPECTED_GAPS
    closed_since = EXPECTED_GAPS - actual_gap
    assert not unexpected_new, (
        "New repositories shipped without unit tests:\n  - "
        + "\n  - ".join(sorted(unexpected_new))
        + "\nWrite a test file under tests/unit/repositories/ or update "
        "EXPECTED_GAPS in this meta test to acknowledge the deferral."
    )
    assert not closed_since, (
        "Tests have been written for repositories still listed in "
        "EXPECTED_GAPS:\n  - "
        + "\n  - ".join(sorted(closed_since))
        + "\nPrune those entries from EXPECTED_GAPS so the backlog stays accurate."
    )

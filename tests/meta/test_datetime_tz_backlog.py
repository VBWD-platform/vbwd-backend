"""S19 meta-oracle — track the naive-datetime backlog.

The codebase is migrating from naive UTC datetimes to timezone-aware
ones (see ``vbwd/utils/datetime_utils.py`` module docstring). Until the
full sweep lands, this test tracks the gap so:

  - new naive ``datetime.now()`` / ``datetime.utcnow()`` calls FAIL the
    test (count exceeds the snapshot below) — forces use of
    :func:`vbwd.utils.datetime_utils.utcnow_aware` instead.
  - shipped fixes that reduce the count fail with a "prune the snapshot"
    hint, keeping the tracker honest.

When the count hits 0 (and BaseModel's columns are TZ-aware), this test
+ the entire S19 sprint can be retired.
"""
import os
import re


# Snapshot of naive datetime calls in production source as of 2026-05-27.
# Excludes tests/, __pycache__, and migration scripts (one-shot data fixes).
EXPECTED_NAIVE_CALL_COUNT = 17


def _scan_naive_datetime_calls() -> list[str]:
    """Return ``file:line: snippet`` for every naive datetime call site."""
    here = os.path.dirname(os.path.abspath(__file__))
    backend = os.path.dirname(os.path.dirname(here))
    pattern = re.compile(r"\bdatetime\.(utcnow|now)\(\s*\)")
    findings: list[str] = []
    for root in (
        os.path.join(backend, "vbwd"),
        os.path.join(backend, "plugins"),
    ):
        for dirpath, _dirs, files in os.walk(root):
            if (
                "__pycache__" in dirpath
                or "/tests/" in dirpath
                or "/migrations/" in dirpath
                or dirpath.endswith("/tests")
            ):
                continue
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                with open(path) as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if pattern.search(line):
                            relative = os.path.relpath(path, backend)
                            findings.append(f"{relative}:{line_number}: {line.strip()}")
    return findings


def test_naive_datetime_call_count_does_not_grow():
    """Snapshot tracker — new naive sites FAIL; pruned sites also fail
    (with a hint to update the snapshot)."""
    findings = _scan_naive_datetime_calls()
    actual_count = len(findings)
    if actual_count > EXPECTED_NAIVE_CALL_COUNT:
        new_sites = actual_count - EXPECTED_NAIVE_CALL_COUNT
        formatted = "\n  - ".join(findings)
        assert False, (
            f"Naive datetime call count grew by {new_sites} (now {actual_count}, "
            f"snapshot was {EXPECTED_NAIVE_CALL_COUNT}). Use "
            "`from vbwd.utils.datetime_utils import utcnow_aware` for any new "
            f"datetime call.\n\nAll sites:\n  - {formatted}"
        )
    if actual_count < EXPECTED_NAIVE_CALL_COUNT:
        assert False, (
            f"Naive datetime call count shrank to {actual_count} (snapshot "
            f"was {EXPECTED_NAIVE_CALL_COUNT}). Update EXPECTED_NAIVE_CALL_COUNT "
            "in this meta test so the tracker stays accurate."
        )


def test_utcnow_aware_exists_and_returns_aware_datetime():
    """The new helper is in place for forward migration."""
    from vbwd.utils.datetime_utils import utcnow_aware

    result = utcnow_aware()
    assert result.tzinfo is not None

"""S15 oracle — operational hygiene that's too easy to drift.

1. ``vbwd_backend`` service in ``docker-compose.server.yaml`` must have
   ``restart: always`` so a single crash auto-recovers (every other prod
   service has it; missing on backend = manual recovery only).

2. CI plugin-clone loop in ``.github/workflows/tests.yml`` must fail
   fast on any clone failure — a green CI run with a half-cloned plugin
   tree is a worse outcome than a red one.
"""
import os
import re


def _backend_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def test_backend_service_has_restart_always():
    """Confirm vbwd_backend gets `restart: always` in the prod compose."""
    compose = os.path.join(_backend_root(), "docker-compose.server.yaml")
    with open(compose) as handle:
        content = handle.read()
    # Find the `vbwd_backend:` block and ensure `restart: always` appears
    # before the next top-level service.
    match = re.search(r"^  vbwd_backend:\s*\n", content, re.MULTILINE)
    assert match is not None, "vbwd_backend service missing from server compose"
    after = content[match.end() :]
    next_service = re.search(r"^  [A-Za-z_][A-Za-z0-9_]*:\s*$", after, re.MULTILINE)
    block = after[: next_service.start()] if next_service else after
    assert re.search(r"^\s*restart:\s*always\s*$", block, re.MULTILINE), (
        "vbwd_backend service must declare `restart: always` so a single "
        "crash auto-restarts."
    )


def test_ci_plugin_clone_fails_fast():
    """The GitHub Actions plugin-clone loop must fail on any clone error.

    Either ``set -euo pipefail`` at the top of the run block or
    ``|| exit 1`` on the clone line is acceptable — both make a failed
    clone abort the workflow before tests run on an incomplete tree.
    """
    workflow = os.path.join(_backend_root(), ".github", "workflows", "tests.yml")
    with open(workflow) as handle:
        content = handle.read()
    # Find the "Install plugins" step's run block.
    # Permissive: the step's display name may be qualified (e.g.
    # "Install plugins (active set — 17 plugins)") and there may be
    # comment lines between `name:` and `run:`.
    step_match = re.search(
        r"- name:\s*Install plugins\b[^\n]*\n(?:\s*#[^\n]*\n)*\s*run:\s*\|\s*\n((?:\s+.*\n)+?)(?=\s*- name:|\Z)",
        content,
    )
    assert step_match is not None, "Couldn't find the 'Install plugins' step"
    run_block = step_match.group(1)
    fail_fast = (
        re.search(r"set\s+-[a-z]*e[a-z]*", run_block)  # set -e / -euo pipefail
        or "|| exit 1" in run_block
        or "|| { " in run_block  # `|| { echo ...; exit 1; }`
    )
    assert fail_fast, (
        "The 'Install plugins' step in .github/workflows/tests.yml must "
        "fail fast (via `set -euo pipefail` or `|| exit 1`) so a broken "
        "plugin clone aborts CI before tests run on an incomplete tree."
    )

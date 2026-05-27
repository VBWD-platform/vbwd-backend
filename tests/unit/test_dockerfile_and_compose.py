"""S03 oracle — migrations must NOT run inside the gunicorn container CMD.

When ``alembic upgrade heads`` is part of the same shell pipeline that
launches gunicorn, a hanging or failing migration blocks the container from
becoming healthy — Kubernetes / load balancers cannot route around it, and
the previous good container has already been replaced. Migrations belong
to a separate one-shot step (compose ``run --rm`` or a dedicated
``vbwd_migrate`` service in compose with restart policy ``no``).
"""
import os
import re


def _backend_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def test_dockerfile_cmd_does_not_run_alembic():
    """The image's CMD launches gunicorn only; migrations live elsewhere."""
    dockerfile = os.path.join(_backend_root(), "container", "python", "Dockerfile")
    with open(dockerfile) as handle:
        content = handle.read()
    cmd_lines = [
        line for line in content.splitlines() if line.strip().startswith("CMD")
    ]
    assert cmd_lines, "Dockerfile must have a CMD line"
    for line in cmd_lines:
        assert "alembic" not in line, (
            f"Dockerfile CMD must not run alembic (found in `{line.strip()}`); "
            "migrations belong in a separate one-shot step so a failed/hung "
            "migration cannot block container readiness."
        )


def _service_block(content: str, service_name: str) -> str | None:
    """Return the YAML block (raw text) for one service, or None if absent.

    Avoids a PyYAML dependency. The compose file is 2-space-indented, so a
    top-level service is ``  <name>:`` and its block ends at the next
    top-level key (``  next:`` at the same indent) or EOF.
    """
    match = re.search(
        r"^  " + re.escape(service_name) + r":\s*$",
        content,
        re.MULTILINE,
    )
    if match is None:
        return None
    start = match.end()
    next_match = re.search(
        r"^  [A-Za-z_][A-Za-z0-9_]*:\s*$", content[start:], re.MULTILINE
    )
    end = start + next_match.start() if next_match else len(content)
    return content[start:end]


def test_compose_server_has_dedicated_migrate_service():
    """``docker-compose.server.yaml`` includes a one-shot vbwd_migrate service
    that runs ``alembic upgrade heads``. Deploy script runs it before
    bringing the backend up."""
    compose = os.path.join(_backend_root(), "docker-compose.server.yaml")
    with open(compose) as handle:
        content = handle.read()
    block = _service_block(content, "vbwd_migrate")
    assert block is not None, (
        "docker-compose.server.yaml must define a `vbwd_migrate` one-shot "
        "service that runs `alembic upgrade heads` against the prod DB."
    )
    # accept either shell form ``command: alembic upgrade heads``
    # or YAML-array form ``command: ["alembic", "upgrade", "heads"]``.
    flexible = r'alembic["\s,]+upgrade["\s,]+heads'
    assert re.search(flexible, block), (
        "vbwd_migrate must run `alembic upgrade heads` (look for the "
        "`command:` key)."
    )
    # one-shot: must NOT auto-restart on completion
    restart_match = re.search(r"^\s*restart:\s*(\S+)\s*$", block, re.MULTILINE)
    assert restart_match is not None, "vbwd_migrate must declare a `restart:` policy."
    restart_value = restart_match.group(1).strip("\"'")
    assert restart_value in {"no", "on-failure"}, (
        f"vbwd_migrate.restart must be 'no' or 'on-failure' (got {restart_value!r}); "
        "it's a one-shot, not a long-running service."
    )

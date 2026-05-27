"""S04 oracle — production secrets must be REQUIRED env vars.

In ``docker-compose.server.yaml`` every secret-shaped variable must use
the required-substitution form ``${VAR:?error}`` so an unset env var
aborts ``docker compose up`` with a clear message instead of silently
substituting empty (or, worse, a baked-in dev placeholder).

The dev compose (``docker-compose.yaml``) deliberately keeps the
``${VAR:-default}`` form so first-time onboarding works without setup —
those defaults are known-public placeholders explicitly labelled
``…-change-in-production``.

Plus a permanent guard that ``.env`` is not tracked by git.
"""
import os
import re


PROD_SECRET_VARS = (
    "VBWD_FLASK_SECRET",
    "VBWD_JWT_SECRET",
    "VBWD_DB_PASSWORD",
    "VBWD_TOKEN_ENCRYPTION_KEY",  # S05 — at-rest token encryption
)


def _backend_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def test_server_compose_secrets_use_required_form():
    """Each prod secret in ``.server.yaml`` must use ``${VAR:?...}``,
    never the bare ``${VAR}`` (silently empty) or ``${VAR:-default}``
    (silently insecure)."""
    compose = os.path.join(_backend_root(), "docker-compose.server.yaml")
    with open(compose) as handle:
        content = handle.read()
    missing_required: list[str] = []
    for variable in PROD_SECRET_VARS:
        # required form: ${VAR:?...} — accept any error message
        required_pattern = r"\$\{" + re.escape(variable) + r":\?[^}]+\}"
        if not re.search(required_pattern, content):
            missing_required.append(variable)
    assert not missing_required, (
        "docker-compose.server.yaml must use the required-substitution form "
        "${VAR:?error} for every secret (missing for: "
        + ", ".join(missing_required)
        + "). "
        "Bare ${VAR} silently defaults to empty; ${VAR:-default} silently "
        "uses an insecure default."
    )


def test_env_file_listed_in_gitignore():
    """The ``.gitignore`` next to ``.env`` (repo-root or backend) must list
    ``.env`` so it can never be accidentally committed."""
    backend = _backend_root()
    # Look in backend/.gitignore first, then the repo root one level up.
    candidates = [
        os.path.join(backend, ".gitignore"),
        os.path.join(os.path.dirname(backend), ".gitignore"),
    ]
    found_pattern = False
    for path in candidates:
        if not os.path.isfile(path):
            continue
        with open(path) as handle:
            lines = [line.strip() for line in handle if line.strip()]
        for entry in lines:
            if entry.startswith("#"):
                continue
            # accept exact `.env` or any glob covering it
            if entry in {".env", "*.env", "**/.env", "/.env"}:
                found_pattern = True
                break
        if found_pattern:
            break
    assert found_pattern, (
        ".env must be listed in .gitignore (checked: "
        + ", ".join(candidates)
        + "). Secrets must never be committed."
    )

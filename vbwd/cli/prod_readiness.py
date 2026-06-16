"""``flask prod-readiness`` — the RC-1 pre-rollout safety checklist (S90, slice 4).

Runs a set of automated checks against the *running* app + its environment and
prints a ✅ / ❌ / ⚠️ checklist. The process exits non-zero if ANY hard check
fails; warnings are surfaced (⚠️) but never change the exit code.

The route-exposure check reuses ``vbwd.security.route_audit.find_unprotected_routes``
— the exact same policy the route-exposure oracle enforces in CI (DRY), so a
green oracle and a green ``prod-readiness`` can never disagree.

The companion manual checklist lives at ``docs/ops/rc1-pre-rollout-checklist.md``.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, cast

import click
from flask import current_app
from flask.cli import with_appcontext

# Check outcomes.
PASS = "pass"
FAIL = "fail"
WARN = "warn"

_ICON = {PASS: "✅", FAIL: "❌", WARN: "⚠️"}

# Log levels considered safe for production (quiet floor).
SAFE_PROD_LOG_LEVELS = {"warning", "error"}


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single readiness check."""

    name: str
    status: str
    detail: str

    @property
    def is_hard_failure(self) -> bool:
        return self.status == FAIL


def _check_production_environment() -> CheckResult:
    """#1 — FLASK_ENV=production and the active config has DEBUG disabled."""
    import os

    flask_env = os.getenv("FLASK_ENV", "")
    debug_off = current_app.config.get("DEBUG") is False
    if flask_env == "production" and debug_off:
        return CheckResult(
            "production environment",
            PASS,
            "FLASK_ENV=production and DEBUG is False.",
        )
    reasons = []
    if flask_env != "production":
        reasons.append(
            f"FLASK_ENV is {flask_env or '(unset)'!r}, expected 'production'"
        )
    if not debug_off:
        reasons.append("DEBUG is not False")
    return CheckResult("production environment", FAIL, "; ".join(reasons))


def _check_secrets_not_default() -> CheckResult:
    """#2 — FLASK_SECRET_KEY / JWT_SECRET_KEY are not the dev defaults."""
    from vbwd.config import DEFAULT_SECRET_KEY

    secret_key = current_app.config.get("SECRET_KEY")
    jwt_secret_key = current_app.config.get("JWT_SECRET_KEY")
    offenders = []
    if not secret_key or secret_key == DEFAULT_SECRET_KEY:
        offenders.append("FLASK_SECRET_KEY is the dev default / unset")
    if not jwt_secret_key or jwt_secret_key == DEFAULT_SECRET_KEY:
        offenders.append("JWT_SECRET_KEY is the dev default / unset")
    if offenders:
        return CheckResult("secrets rotated", FAIL, "; ".join(offenders))
    return CheckResult(
        "secrets rotated", PASS, "FLASK_SECRET_KEY and JWT_SECRET_KEY are non-default."
    )


def _check_debug_endpoints_off() -> CheckResult:
    """#3 — ENABLE_DEBUG_ENDPOINTS falsy (/_routes + /_seed_status are 404)."""
    if current_app.config.get("ENABLE_DEBUG_ENDPOINTS"):
        return CheckResult(
            "debug endpoints disabled",
            FAIL,
            "ENABLE_DEBUG_ENDPOINTS is truthy; /_routes and /_seed_status are exposed.",
        )
    return CheckResult(
        "debug endpoints disabled",
        PASS,
        "ENABLE_DEBUG_ENDPOINTS off; /_routes and /_seed_status are 404.",
    )


def _check_log_level() -> CheckResult:
    """#4 (WARN) — VBWD_LOG_LEVEL should be warning/error in production."""
    import os

    level = (
        str(
            current_app.config.get("LOG_LEVEL") or os.getenv("VBWD_LOG_LEVEL") or "info"
        )
        .strip()
        .lower()
    )
    if level in SAFE_PROD_LOG_LEVELS:
        return CheckResult("log level", PASS, f"VBWD_LOG_LEVEL={level} (quiet floor).")
    return CheckResult(
        "log level",
        WARN,
        f"VBWD_LOG_LEVEL={level}; set 'warning' or 'error' so the info stream "
        "stops growing in production.",
    )


def _check_route_exposure() -> CheckResult:
    """#5 — every route is provably protected or deliberately allow-listed."""
    from vbwd.security.route_audit import describe_offender, find_unprotected_routes

    offenders = find_unprotected_routes(current_app)
    if not offenders:
        return CheckResult(
            "route exposure", PASS, "Every route is protected or allow-listed."
        )
    lines = "; ".join(
        describe_offender(route)
        for route in sorted(offenders, key=lambda route: route.path)
    )
    return CheckResult(
        "route exposure",
        FAIL,
        f"{len(offenders)} unprotected route(s): {lines}",
    )


def _check_no_demo_seed_markers() -> CheckResult:
    """#6 (WARN) — no load-test / demo seed markers in prod tables.

    Core has no cheap, plugin-agnostic demo/loadtest detector (the demo-slug /
    ``loadtest-`` helpers live inside individual plugin exchangers, which core
    must not import). So this is a manual-review WARN rather than a hard gate;
    the manual checklist covers verifying demo data was not seeded into prod.
    """
    return CheckResult(
        "no demo/load-test seed data",
        WARN,
        "No core-level demo/load-test detector (plugin-specific). Verify "
        "manually that prod was not populated with demo or loadtest- data.",
    )


def _check_sanitized_error_handler() -> CheckResult:
    """#7 — the registered 500 handler returns a sanitized, generic body.

    Invokes the app's registered error handler with a sentinel exception whose
    message embeds a secret marker, then asserts the rendered body neither
    echoes the message nor leaks a traceback.
    """
    secret_marker = "SENTINEL_TRACEBACK_LEAK_MARKER_x9z"
    handler = _resolve_error_handler(500)
    if handler is None:
        return CheckResult(
            "sanitized error responses",
            FAIL,
            "No registered 500 error handler found.",
        )

    error = Exception(secret_marker)
    try:
        body = _render_handler_body(handler, error)
    except Exception as exc:
        # A broken handler is itself a readiness failure; report it as a result
        # rather than letting the exception abort the whole checklist run.
        return CheckResult(
            "sanitized error responses",
            FAIL,
            f"500 handler raised while rendering: {type(exc).__name__}.",
        )

    leaks_marker = secret_marker in body
    leaks_traceback = "Traceback (most recent call last)" in body
    if leaks_marker or leaks_traceback:
        return CheckResult(
            "sanitized error responses",
            FAIL,
            "500 handler leaks the exception message or a traceback.",
        )
    return CheckResult(
        "sanitized error responses",
        PASS,
        "500 handler returns a generic, sanitized body.",
    )


def _resolve_error_handler(status_code: int):
    """Return the app's registered handler callable for ``status_code`` or None."""
    by_code = current_app.error_handler_spec.get(None, {}).get(status_code)
    if not by_code:
        return None
    # Flask keys each status-code bucket by exception class; the catch-all is
    # stored under the ``None`` key. ``cast`` to a plain dict so mypy accepts
    # the ``None`` lookup against Flask's strict ``type[Exception]`` key type.
    by_exception_class = cast(Dict[Any, Any], by_code)
    return by_exception_class.get(None) or next(iter(by_exception_class.values()))


def _render_handler_body(handler, error) -> str:
    """Invoke ``handler(error)`` inside a request context and return its body."""
    with current_app.test_request_context("/api/v1/_readiness_probe"):
        response = current_app.make_response(handler(error))
        return response.get_data(as_text=True)


def _check_cors_not_wildcard() -> CheckResult:
    """#8 — CORS / allowed origins are not the ``*`` wildcard in production."""
    origins = current_app.config.get("CORS_ALLOWED_ORIGINS")
    if origins is None:
        return CheckResult(
            "CORS origins not wildcard",
            PASS,
            "No CORS_ALLOWED_ORIGINS configured (no wildcard cross-origin grant).",
        )
    normalized = _normalize_origins(origins)
    if "*" in normalized:
        return CheckResult(
            "CORS origins not wildcard",
            FAIL,
            "CORS_ALLOWED_ORIGINS contains '*'; pin explicit origins in production.",
        )
    return CheckResult(
        "CORS origins not wildcard",
        PASS,
        f"CORS_ALLOWED_ORIGINS pinned to {len(normalized)} explicit origin(s).",
    )


def _normalize_origins(origins) -> List[str]:
    """Normalize a CORS origins config (str CSV or list) to a list of strings."""
    if isinstance(origins, str):
        return [item.strip() for item in origins.split(",") if item.strip()]
    return [str(item).strip() for item in origins]


def _run_all_checks() -> List[CheckResult]:
    """Run every readiness check in checklist order."""
    return [
        _check_production_environment(),
        _check_secrets_not_default(),
        _check_debug_endpoints_off(),
        _check_log_level(),
        _check_route_exposure(),
        _check_no_demo_seed_markers(),
        _check_sanitized_error_handler(),
        _check_cors_not_wildcard(),
    ]


def _emit_report(results: List[CheckResult]) -> Optional[List[CheckResult]]:
    """Print the checklist and return the hard failures (empty list if clean)."""
    click.echo("PROD-READINESS — RC-1 pre-rollout checklist")
    click.echo("=" * 52)
    for result in results:
        click.echo(f"{_ICON[result.status]}  {result.name}: {result.detail}")

    hard_failures = [result for result in results if result.is_hard_failure]
    warnings = [result for result in results if result.status == WARN]

    click.echo("-" * 52)
    if hard_failures:
        click.echo(f"FAILED — {len(hard_failures)} hard check(s) not met:")
        for result in hard_failures:
            click.echo(f"  ❌ {result.name}")
    else:
        click.echo("PASSED — all hard checks met.")
    if warnings:
        click.echo(f"{len(warnings)} warning(s) (non-blocking):")
        for result in warnings:
            click.echo(f"  ⚠️  {result.name}")
    return hard_failures


@click.command("prod-readiness")
@with_appcontext
def prod_readiness_command():
    """
    Run the RC-1 pre-rollout readiness checklist against the running app.

    Exits 0 only if every HARD check passes; warnings (⚠️) are surfaced but do
    not change the exit code. See docs/ops/rc1-pre-rollout-checklist.md for the
    full (automated + manual) checklist.

    Usage:
        FLASK_ENV=production flask prod-readiness
    """
    results = _run_all_checks()
    hard_failures = _emit_report(results)
    if hard_failures:
        raise SystemExit(1)

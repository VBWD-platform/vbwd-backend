"""Repo-wide pytest hooks.

Connection-leak guard
---------------------
Most test suites here build their own Flask app per test (or per module), and
each app gets its own SQLAlchemy engine with a connection pool. Those engines
are almost never disposed, so their pooled connections linger and accumulate
across a full-suite run until PostgreSQL refuses new ones
("FATAL: sorry, too many clients already") and every later test errors at setup.

We track every engine the moment it opens a connection (cheap, via a global
SQLAlchemy event) and dispose them after each test, returning pooled connections
to the server. Pooling still works *within* a test (individual tests stay fast),
but connections can't pile up *between* tests — the full suite stays well under
``max_connections``.

Test-run licence
----------------
A keyless install grants no licensed feature, so a licence-requiring plugin
never activates without a real licence. Rather than weaken that gate, every
test session holds a test licence: a throwaway Ed25519 key is generated, the
licence env vars point at it, and a wildcard licence for the test instance is
minted (``vbwd.testing.license_harness``). ``create_app(config_dict)`` — the
factory every suite uses — never loads ``vbwd.config``, so the same two licence
keys are also defaulted into those dicts. Tests that model a keyless install
pass ``LICENSE_PUBLIC_KEY: None`` (and an empty ``LICENSE_KEYS_DIR``) to
``create_app`` / ``build_license_environment`` explicitly; an explicit value
always wins.
"""
import base64
import functools
import os
import shutil
import tempfile
import weakref

import pytest
from nacl.signing import SigningKey
from sqlalchemy import event
from sqlalchemy.engine import Engine

_engines: "weakref.WeakSet[Engine]" = weakref.WeakSet()
_TEST_LICENSE_DIR_PREFIX = "vbwd-test-license-"
_test_license_dir = None


def _install_test_license() -> None:
    """Point the licence env at a session-scoped, test-only signing key.

    MUST run before anything imports ``vbwd``: ``vbwd.config`` reads the
    licence env vars at import time. Overrides any developer/CI value so the
    run is hermetic. Hence the env is set first and the ``vbwd`` helper is
    imported only afterwards.
    """
    global _test_license_dir
    _test_license_dir = tempfile.mkdtemp(prefix=_TEST_LICENSE_DIR_PREFIX)
    keys_dir = os.path.join(_test_license_dir, "keys")
    signing_key = SigningKey.generate()
    # base64url without padding — the format ``Ed25519SignatureVerifier``
    # parses (``license_key.base64url_encode``; not importable before env).
    public_key = base64.urlsafe_b64encode(bytes(signing_key.verify_key))
    os.environ["VBWD_LICENSE_PUBLIC_KEY"] = public_key.rstrip(b"=").decode("ascii")
    os.environ["VBWD_LICENSE_KEYS_DIR"] = keys_dir

    from vbwd.config import get_database_url
    from vbwd.testing.license_harness import write_test_licenses

    write_test_licenses(signing_key, keys_dir, get_database_url())
    _default_license_into_dict_configs(
        {
            "LICENSE_PUBLIC_KEY": os.environ["VBWD_LICENSE_PUBLIC_KEY"],
            "LICENSE_KEYS_DIR": keys_dir,
        }
    )


def _default_license_into_dict_configs(license_config: dict) -> None:
    """Default ``license_config`` into every ``create_app(config_dict)`` call.

    The dict path skips ``vbwd.config`` (so the env never reaches it); keys the
    caller sets explicitly win, which is how keyless-install tests opt out.
    """
    import vbwd
    import vbwd.app

    original_create_app = vbwd.app.create_app

    @functools.wraps(original_create_app)
    def create_app_with_test_license(config=None):
        if config:
            config = {**license_config, **config}
        return original_create_app(config)

    vbwd.app.create_app = create_app_with_test_license
    vbwd.create_app = create_app_with_test_license


def pytest_configure(config):
    """Install the test-run licence; register the ``no_db_isolation`` marker.

    The marker is registered once for the whole repo.

    Plugin integration suites isolate each test in a rolled-back transaction
    (``vbwd/testing/integration_db.rollback_isolation``), which binds the scoped
    session to one connection and rolls it back. A test marked
    ``no_db_isolation`` runs WITHOUT that wrapper — it needs a real
    ``db.engine`` (e.g. a migration test that opens its OWN connection and rolls
    back itself, or a race spec that contends across genuinely separate
    connections) and is responsible for cleaning up anything it commits.
    """
    _install_test_license()
    config.addinivalue_line(
        "markers",
        "no_db_isolation: run without the rolled-back-transaction isolation "
        "(the test manages its own connection/cleanup).",
    )


def pytest_unconfigure(config):
    """Remove the session's throwaway licence directory."""
    if _test_license_dir is not None:
        shutil.rmtree(_test_license_dir, ignore_errors=True)


@event.listens_for(Engine, "engine_connect")
def _remember_engine(connection, *args):
    """Record each engine as it hands out a connection."""
    engine = getattr(connection, "engine", None)
    if engine is not None:
        _engines.add(engine)


@pytest.fixture(autouse=True)
def _dispose_sqlalchemy_engines():
    """Release each test's DB resources afterwards.

    First close the shared scoped session — an uncommitted session left "idle in
    transaction" keeps table locks, which later deadlocks another test's
    ``db.drop_all()`` (``DROP TABLE`` blocks on the lock forever). Then dispose
    the engines so their pooled connections return to the server.

    Also reset the global Flask-Limiter window BEFORE each test. The limiter is a
    process-wide singleton backed by a shared (Redis) store that ``init_app``
    does not swap for the test config's ``memory://``, so per-route windows like
    ``/auth/login`` ("30 per minute") otherwise accumulate across every test in
    the run (and across runs, since the store is never flushed) until later
    logins 429. A clean window per test makes the suite deterministic; the
    dedicated rate-limit specs are self-contained within one test, so they are
    unaffected.
    """
    try:
        from vbwd.extensions import limiter

        limiter.reset()
    except Exception:
        # Best-effort: a limiter that cannot reset must never fail a test.
        pass
    yield
    try:
        from vbwd.extensions import db

        db.session.remove()
    except Exception:
        pass
    for engine in list(_engines):
        try:
            engine.dispose()
        except Exception:
            # A best-effort cleanup must never fail a test.
            pass
    _engines.clear()

import multiprocessing
import os

from vbwd.config import build_engine_options

bind = "0.0.0.0:5000"

# S48.1 — connection-pool / worker tuning.
#
# INVARIANT (guarded by tests/unit/test_connection_pool_tuning.py):
#   workers x (pool_size + max_overflow) + reserve <= Postgres max_connections
#
# Postgres ships max_connections=200. Defaults: pool_size=10, max_overflow=10
# (20 conns/worker). Real horizontal scale uses pgbouncer (S48.4), not a
# bigger ceiling. All knobs are env-driven so prod and CI share this code.

# Workers default to (2 x CPU) + 1 rather than a hardcoded 4, so the box uses
# its cores; WEB_CONCURRENCY (Heroku/12-factor convention) or GUNICORN_WORKERS
# override it. Whatever the count, the invariant above must hold against the
# pool size for the target Postgres max_connections.
_default_workers = (2 * multiprocessing.cpu_count()) + 1
workers = int(
    os.getenv("WEB_CONCURRENCY", os.getenv("GUNICORN_WORKERS", _default_workers))
)

# meinchat's SSE endpoint (GET /api/v1/messaging/stream) holds a connection open
# for the whole browser session. With `sync` workers each open stream parks an
# ENTIRE worker, so a handful of chat tabs starves every other request (the prod
# "one user blocks everyone" freeze). `gthread` lets one worker serve many
# long-lived connections concurrently — a thread blocked on the SSE queue
# releases the GIL, so streams no longer block normal API traffic. gthread (not
# gevent) is required here because the event bus uses a blocking `queue.Queue`,
# which cooperates with OS threads but NOT with un-monkey-patched greenlets.
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "gthread")

# Threads default to the DB pool size: more request threads than connections
# just makes threads block on the pool, so align them. Env override stays.
_default_threads = build_engine_options()["pool_size"]
threads = int(os.getenv("GUNICORN_THREADS", _default_threads))

# Worker timeout. A 30 s load-shedding value (recycle a worker stuck on an
# overloaded DB instead of hanging ~2 min) is too low now that synchronous LLM
# endpoints are pervasive — cms-ai generate, bot replies, and the S97/S98 LLM
# paths legitimately take 30-60 s+, and a request exceeding `timeout` is
# SIGKILLed → nginx 502 (e.g. an article generates no body). 120 s covers those
# (nginx already allows 300 s on /api/v1/plugins/cms-ai/) while still bounding a
# truly hung worker. Override per deployment via GUNICORN_TIMEOUT; lower it where
# no LLM endpoints are served and tight p99 load-shedding matters more.
timeout = int(os.getenv("GUNICORN_TIMEOUT", 120))
keepalive = 5
max_requests = 1000
max_requests_jitter = 50

# Logging
accesslog = "-"  # stdout
errorlog = "-"  # stderr
loglevel = os.getenv("LOG_LEVEL", "info")

# For development with reload
reload = os.getenv("FLASK_ENV") == "development"

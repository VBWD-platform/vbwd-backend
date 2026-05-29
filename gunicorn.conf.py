import os

bind = "0.0.0.0:5000"
workers = int(os.getenv("GUNICORN_WORKERS", 4))
# meinchat's SSE endpoint (GET /api/v1/messaging/stream) holds a connection open
# for the whole browser session. With `sync` workers each open stream parks an
# ENTIRE worker, so a handful of chat tabs starves every other request (the prod
# "one user blocks everyone" freeze). `gthread` lets one worker serve many
# long-lived connections concurrently — a thread blocked on the SSE queue
# releases the GIL, so streams no longer block normal API traffic. gthread (not
# gevent) is required here because the event bus uses a blocking `queue.Queue`,
# which cooperates with OS threads but NOT with un-monkey-patched greenlets.
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "gthread")
threads = int(os.getenv("GUNICORN_THREADS", 64))
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50

# Logging
accesslog = "-"  # stdout
errorlog = "-"  # stderr
loglevel = os.getenv("LOG_LEVEL", "info")

# For development with reload
reload = os.getenv("FLASK_ENV") == "development"

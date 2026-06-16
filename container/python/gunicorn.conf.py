import os

bind = "0.0.0.0:5000"
workers = int(os.getenv("GUNICORN_WORKERS", 4))
worker_class = "sync"
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50

# Logging
# S90 G3 — write access/error to stdout/stderr ("-") so Docker's json-file
# driver (max-size/max-file, set in the prod compose) rotates them. Writing to
# /app/logs/*.log would grow unbounded — Docker only rotates container streams.
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")

# For development with reload
reload = os.getenv("FLASK_ENV") == "development"

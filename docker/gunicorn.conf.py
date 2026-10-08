"""Gunicorn settings for the production web container."""

import multiprocessing
import os

bind = "0.0.0.0:8000"
worker_class = "uvicorn_worker.UvicornWorker"
# Async workers handle many connections each (live feeds hold one open), so a
# few per CPU is plenty; WEB_CONCURRENCY overrides.
workers = int(os.environ.get("WEB_CONCURRENCY", min(2 * multiprocessing.cpu_count() + 1, 5)))
timeout = 60
graceful_timeout = 30
keepalive = 5
# Recycle workers now and then to contain slow memory growth.
max_requests = 2000
max_requests_jitter = 200
# Caddy is the only client; it sets X-Forwarded-Proto/For.
forwarded_allow_ips = "*"
accesslog = "-"
errorlog = "-"

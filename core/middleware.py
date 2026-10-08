import logging

import redis
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.utils.cache import patch_vary_headers

logger = logging.getLogger(__name__)

HEALTH_PATH = "/healthz/"


def client_ip(request):
    """The reader's address: Caddy's X-Real-IP (always set by it), else the socket peer.

    The web container is reachable only through Caddy in production, so the
    header can't be supplied by anyone else.
    """
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")


def check_health():
    """Return ({component: "ok" | "error"}, healthy) for the database and Redis."""
    status = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        status["database"] = "ok"
    except Exception:
        logger.exception("Health check: database unavailable")
        status["database"] = "error"
    try:
        client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        status["redis"] = "ok"
    except Exception:
        logger.exception("Health check: Redis unavailable")
        status["redis"] = "error"
    return status, all(value == "ok" for value in status.values())


class HealthCheckMiddleware:
    """Answer /healthz/ before host validation and the HTTPS redirect.

    Docker and uptime monitors call it by IP or as localhost over plain HTTP,
    which the rest of the stack would (rightly) reject in production.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != HEALTH_PATH:
            return self.get_response(request)
        status, healthy = check_health()
        response = JsonResponse(status, status=200 if healthy else 503)
        response["Cache-Control"] = "no-store"
        return response


class HtmxVaryMiddleware:
    """Responses differ for HTMX requests (partials), so caches must key on it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        patch_vary_headers(response, ["HX-Request"])
        return response

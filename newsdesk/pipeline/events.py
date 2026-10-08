"""The live activity feed.

Every event is published on a Redis channel for the article, so anyone with
the workspace open sees it at once (server-sent events, see
`newsdesk.live`). Events worth keeping are also stored as AgentEvent rows,
so the feed can be replayed after a reconnect. Streamed text (the writer
typing) is published but not stored.

Publishing never breaks a run: if Redis is unreachable the event is still
stored and the page falls back to polling.
"""

import json
import logging
import time

import redis
from django.conf import settings

from newsdesk.models import AgentEvent

logger = logging.getLogger(__name__)

# Kinds that tell the page to reload: the run is over.
RUN_END = "run_end"

_client = None


def channel(workspace_id):
    return f"newsdesk:ws:{workspace_id}"


def redis_client():
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=0.5, socket_timeout=1)
    return _client


def publish(workspace_id, payload):
    if not settings.NEWSDESK_LIVE_EVENTS:
        return
    try:
        redis_client().publish(channel(workspace_id), json.dumps(payload, default=str))
    except redis.RedisError as exc:
        logger.warning("Could not publish a live event: %s", exc)


def payload_for(run, kind, message, step=None, data=None, event_id=None):
    return {
        "id": event_id,
        "run": run.pk,
        "step": step.pk if step else None,
        "kind": kind,
        "message": message,
        "data": data or {},
    }


def emit(run, kind, message, step=None, data=None, persist=True):
    data = data or {}
    event = None
    if persist:
        event = AgentEvent.objects.create(run=run, step=step, kind=kind, message=message[:2000], data=data)
    publish(run.workspace_id, payload_for(run, kind, message, step, data, event.pk if event else None))
    return event


class TextBuffer:
    """Collects streamed text and publishes it in chunks (a few per second, not per token)."""

    def __init__(self, run, step, interval=0.3, size=240):
        self.run, self.step = run, step
        self.interval, self.size = interval, size
        self.parts, self.last = [], time.monotonic()

    def add(self, text):
        self.parts.append(text)
        if sum(len(p) for p in self.parts) >= self.size or time.monotonic() - self.last >= self.interval:
            self.flush()

    def flush(self):
        if self.parts:
            emit(self.run, "text", "".join(self.parts), step=self.step, persist=False)
            self.parts = []
        self.last = time.monotonic()

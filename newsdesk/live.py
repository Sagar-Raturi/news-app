"""Server-sent events for the workspace's live activity feed.

An async view (served under ASGI) that first replays stored events newer than
the page the editor loaded, then relays new ones from Redis as they happen.
It lives outside the Wagtail admin URLs because Wagtail's admin decorators
are synchronous; it does its own permission check instead.
"""

import asyncio
import json

import redis.asyncio as aioredis
from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import Http404, HttpResponseForbidden, StreamingHttpResponse

from .models import AgentEvent, ArticleWorkspace
from .pipeline.events import channel, payload_for

HEARTBEAT_SECONDS = 15
STREAM_SECONDS = 10 * 60  # the browser reconnects by itself after this
REPLAY_LIMIT = 500


def sse(payload):
    head = f"id: {payload['id']}\n" if payload.get("id") else ""
    return f"{head}data: {json.dumps(payload, default=str)}\n\n"


def may_watch(user):
    return user.is_authenticated and user.has_perm("wagtailadmin.access_admin") and user.has_perm(
        "newsdesk.view_articleworkspace"
    )


def stored_events(workspace_id, after):
    events = (
        AgentEvent.objects.filter(run__workspace_id=workspace_id, pk__gt=after)
        .select_related("run", "step")
        .order_by("pk")[:REPLAY_LIMIT]
    )
    return [payload_for(e.run, e.kind, e.message, e.step, e.data, e.pk) for e in events]


async def event_stream(workspace_id, after, client=None, stream_seconds=STREAM_SECONDS):
    client = client or aioredis.from_url(settings.CELERY_BROKER_URL)
    pubsub = client.pubsub()
    await pubsub.subscribe(channel(workspace_id))
    try:
        yield "retry: 3000\n\n"
        # Subscribed first, then replay, so nothing falls between the two.
        last = after
        for payload in await sync_to_async(stored_events)(workspace_id, after):
            last = payload["id"]
            yield sse(payload)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + stream_seconds
        while loop.time() < deadline:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=HEARTBEAT_SECONDS)
            if message is None:
                yield ": ping\n\n"
                continue
            payload = json.loads(message["data"])
            if payload.get("id") and payload["id"] <= last:
                continue
            if payload.get("id"):
                last = payload["id"]
            yield sse(payload)
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
        await client.aclose()


async def workspace_events(request, pk):
    user = await request.auser()
    if not await sync_to_async(may_watch)(user):
        return HttpResponseForbidden()
    if not await ArticleWorkspace.objects.filter(pk=pk).aexists():
        raise Http404
    try:
        after = int(request.headers.get("Last-Event-ID") or request.GET.get("after") or 0)
    except ValueError:
        after = 0
    response = StreamingHttpResponse(event_stream(pk, after), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # don't let a proxy buffer the stream
    return response

"""Live activity feed: Redis publishing, the SSE stream, and the page wiring."""

import json
from unittest import mock

import redis
from asgiref.sync import sync_to_async
from django.test import override_settings
from django.urls import reverse

from newsdesk.jobs import start_run
from newsdesk.live import event_stream
from newsdesk.models import AgentDefinition, AgentEvent, AgentRun
from newsdesk.pipeline import events
from newsdesk.pipeline.fake import FakeCaller, ScriptedCaller
from newsdesk.pipeline.llm import AgentRequest
from newsdesk.pipeline.runner import Pipeline

from .base import WorkspaceTestCase, writer_only
from .test_generation import full_draft


class FakePubSub:
    def __init__(self, messages):
        self.messages = list(messages)
        self.channels = []

    async def subscribe(self, name):
        self.channels.append(name)

    async def unsubscribe(self):
        pass

    async def aclose(self):
        pass

    async def get_message(self, ignore_subscribe_messages=True, timeout=None):
        if self.messages:
            return {"type": "message", "data": json.dumps(self.messages.pop(0))}
        return None


class FakeAsyncRedis:
    def __init__(self, messages=()):
        self._pubsub = FakePubSub(messages)
        self.closed = False

    def pubsub(self):
        return self._pubsub

    async def aclose(self):
        self.closed = True


class PublishTests(WorkspaceTestCase):
    def setUp(self):
        self.ws = self.make_workspace()
        self.run = AgentRun.objects.create(workspace=self.ws)

    @override_settings(NEWSDESK_LIVE_EVENTS=True)
    def test_events_are_stored_and_published_on_the_articles_channel(self):
        client = mock.MagicMock()
        with mock.patch.object(events, "redis_client", return_value=client):
            event = events.emit(self.run, "status", "Agents started")
            events.emit(self.run, "text", "Onion prices", persist=False)
        channel, body = client.publish.call_args_list[0].args
        self.assertEqual(channel, f"newsdesk:ws:{self.ws.pk}")
        self.assertEqual(json.loads(body)["id"], event.pk)
        self.assertEqual(json.loads(client.publish.call_args_list[1].args[1])["id"], None)
        self.assertEqual(AgentEvent.objects.count(), 1)  # streamed text isn't stored

    @override_settings(NEWSDESK_LIVE_EVENTS=True)
    def test_redis_trouble_never_breaks_a_run(self):
        client = mock.MagicMock()
        client.publish.side_effect = redis.ConnectionError("down")
        with mock.patch.object(events, "redis_client", return_value=client):
            event = events.emit(self.run, "status", "Still stored")
        self.assertTrue(AgentEvent.objects.filter(pk=event.pk).exists())

    def test_streamed_text_is_published_in_chunks(self):
        buffer = events.TextBuffer(self.run, None, interval=60, size=20)
        with mock.patch.object(events, "emit") as emit:
            for word in ["Onion ", "prices ", "rose ", "sharply ", "this ", "month."]:
                buffer.add(word)
            buffer.flush()
        sent = "".join(call.args[2] for call in emit.call_args_list)
        self.assertEqual(sent, "Onion prices rose sharply this month.")
        self.assertLess(emit.call_count, 6)

    def test_a_finished_run_tells_the_page_to_reload(self):
        with mock.patch("newsdesk.jobs._enqueue"):
            run = start_run(self.make_workspace(self.make_topic("Other")), AgentRun.Kind.GENERATE, self.editor)
        Pipeline(run, caller=ScriptedCaller(writer_only(full_draft()))).execute()
        self.assertTrue(run.events.filter(kind=events.RUN_END).exists())


class StreamTests(WorkspaceTestCase):
    def setUp(self):
        self.ws = self.make_workspace()
        self.run = AgentRun.objects.create(workspace=self.ws)
        self.old = AgentEvent.objects.create(run=self.run, kind="status", message="Before the page loaded")
        self.missed = AgentEvent.objects.create(run=self.run, kind="step", message="Writer started")

    async def collect(self, client, after, limit=6):
        chunks = []
        stream = event_stream(self.ws.pk, after, client=client, stream_seconds=0.05)
        async for chunk in stream:
            chunks.append(chunk)
            if len(chunks) >= limit:
                break
        await stream.aclose()
        return chunks

    async def test_replays_missed_events_then_relays_new_ones_once(self):
        live = [
            {"id": self.missed.pk, "kind": "step", "message": "duplicate of the replay"},
            {"id": None, "kind": "text", "message": "Onion prices"},
        ]
        client = FakeAsyncRedis(live)
        chunks = await self.collect(client, after=self.old.pk)
        text = "".join(chunks)
        self.assertTrue(chunks[0].startswith("retry:"))
        self.assertIn(f"id: {self.missed.pk}\n", text)
        self.assertNotIn("Before the page loaded", text)
        self.assertNotIn("duplicate of the replay", text)
        self.assertIn("Onion prices", text)
        self.assertIn(": ping", text)
        self.assertEqual(client.pubsub().channels, [f"newsdesk:ws:{self.ws.pk}"])
        self.assertTrue(client.closed)

    async def test_other_articles_events_are_not_replayed(self):
        other = await sync_to_async(self.make_workspace)(await sync_to_async(self.make_topic)("Other"))
        other_run = await AgentRun.objects.acreate(workspace=other)
        await AgentEvent.objects.acreate(run=other_run, kind="status", message="Other article")
        text = "".join(await self.collect(FakeAsyncRedis(), after=0, limit=4))
        self.assertNotIn("Other article", text)
        self.assertIn("Writer started", text)

    async def test_only_newsroom_staff_can_watch(self):
        url = reverse("newsdesk_live_events", args=[self.ws.pk])
        self.assertEqual((await self.async_client.get(url)).status_code, 403)

        seen = {}

        async def short_stream(workspace_id, after):
            seen.update(workspace_id=workspace_id, after=after)
            yield "retry: 3000\n\n"

        await self.async_client.aforce_login(self.writer)
        with mock.patch("newsdesk.live.event_stream", short_stream):
            response = await self.async_client.get(url + "?after=5")
            body = b"".join([chunk async for chunk in response.streaming_content])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        self.assertEqual(body, b"retry: 3000\n\n")
        self.assertEqual(seen, {"workspace_id": self.ws.pk, "after": 5})
        missing = await self.async_client.get(reverse("newsdesk_live_events", args=[999999]))
        self.assertEqual(missing.status_code, 404)


class PageWiringTests(WorkspaceTestCase):
    def test_page_subscribes_only_while_agents_work(self):
        ws = self.make_workspace()
        url = reverse("newsdesk_articles:detail", args=[ws.pk])
        self.client.force_login(self.editor)
        self.assertNotContains(self.client.get(url), "data-events=")
        run = AgentRun.objects.create(workspace=ws)
        event = AgentEvent.objects.create(run=run, kind="status", message="Queued")
        response = self.client.get(url)
        self.assertContains(response, f'/newsdesk/live/{ws.pk}/events/?after={event.pk}')
        self.assertContains(response, "every 2s[!window.ndLive]")

    @override_settings(NEWSDESK_FAKE_DELAY=0.0001)
    def test_fake_agents_stream_their_demo_text(self):
        seen = []
        request = AgentRequest(
            agent=AgentDefinition.for_role("writer"),
            system=[],
            messages=[{"role": "user", "content": "<brief>\nTopic: Onions\nBrief: Why?\n</brief>"}],
            on_event=lambda kind, message, data=None: seen.append((kind, message)),
        )
        FakeCaller().call(request)
        streamed = "".join(message for kind, message in seen if kind == "text")
        self.assertIn("Onions (demo draft)", streamed)

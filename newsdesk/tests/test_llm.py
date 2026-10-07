"""The Claude call layer, against a mocked SDK client (no network)."""

from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import anthropic
import httpx2

from newsdesk.models import AgentDefinition
from newsdesk.pipeline.llm import AgentError, AgentRequest, AnthropicCaller, TransientAgentError, estimate_cost
from newsdesk.pipeline.schemas import FullDraft

from .base import WorkspaceTestCase
from .test_generation import full_draft


def message(content=(), stop_reason="end_turn", parsed=None, usage=None, model="claude-opus-5-5"):
    return SimpleNamespace(
        content=list(content),
        stop_reason=stop_reason,
        parsed_output=parsed,
        model=model,
        usage=usage
        or SimpleNamespace(
            input_tokens=1000,
            output_tokens=500,
            cache_read_input_tokens=2000,
            cache_creation_input_tokens=0,
            server_tool_use=None,
        ),
    )


class FakeStream:
    def __init__(self, final, events=()):
        self.final, self.events = final, list(events)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_message(self):
        return self.final


def client_with(*streams, error=None):
    client = mock.MagicMock()
    if error is not None:
        client.beta.messages.stream.side_effect = error
    else:
        client.beta.messages.stream.side_effect = list(streams)
    return client


def status_error(cls, code):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(code, request=request), body=None)


class AnthropicCallerTests(WorkspaceTestCase):
    def setUp(self):
        self.writer_agent = AgentDefinition.for_role("writer")

    def request(self, **kwargs):
        kwargs.setdefault("agent", self.writer_agent)
        kwargs.setdefault("system", [{"type": "text", "text": "You write."}])
        kwargs.setdefault("messages", [{"role": "user", "content": "Write."}])
        return AgentRequest(**kwargs)

    def test_streams_with_the_agents_settings_and_returns_parsed_output(self):
        events = [SimpleNamespace(type="text", text="Onion ")]
        client = client_with(FakeStream(message(parsed=full_draft()), events))
        seen = []
        response = AnthropicCaller(client).call(
            self.request(output_format=FullDraft, on_event=lambda kind, msg, data=None: seen.append((kind, msg)))
        )
        kwargs = client.beta.messages.stream.call_args.kwargs
        self.assertEqual((kwargs["model"], kwargs["max_tokens"]), ("claude-opus-5-5", self.writer_agent.max_tokens))
        self.assertEqual(kwargs["output_config"], {"effort": "high"})
        self.assertEqual(kwargs["output_format"], FullDraft)
        self.assertEqual(kwargs["fallbacks"], "default")
        self.assertNotIn("temperature", kwargs)
        self.assertEqual(response.parsed.headline, "Onion prices keep spiking")
        self.assertEqual((response.usage.input_tokens, response.usage.cache_read_tokens), (1000, 2000))
        self.assertIn(("text", "Onion "), seen)

    def test_model_and_effort_come_from_the_admin(self):
        self.writer_agent.model, self.writer_agent.effort = "claude-sonnet-5-5", "low"
        client = client_with(FakeStream(message(parsed=full_draft())))
        AnthropicCaller(client).call(self.request(output_format=FullDraft))
        kwargs = client.beta.messages.stream.call_args.kwargs
        self.assertEqual((kwargs["model"], kwargs["output_config"]), ("claude-sonnet-5-5", {"effort": "low"}))

        self.writer_agent.model = "claude-haiku-4-5"
        client = client_with(FakeStream(message(parsed=full_draft())))
        AnthropicCaller(client).call(self.request(output_format=FullDraft))
        self.assertNotIn("output_config", client.beta.messages.stream.call_args.kwargs)

    def test_bad_endings_fail_cleanly(self):
        for stop_reason, text in [("refusal", "declined"), ("max_tokens", "length limit")]:
            client = client_with(FakeStream(message(stop_reason=stop_reason)))
            with self.assertRaisesMessage(AgentError, text):
                AnthropicCaller(client).call(self.request())
        client = client_with(FakeStream(message(content=[SimpleNamespace(type="text", text="not json")])))
        with self.assertRaisesMessage(AgentError, "usable output"):
            AnthropicCaller(client).call(self.request(output_format=FullDraft))

    def test_errors_are_split_into_transient_and_permanent(self):
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        transient = [
            status_error(anthropic.RateLimitError, 429),
            status_error(anthropic.InternalServerError, 529),
            anthropic.APIConnectionError(request=request),
        ]
        for error in transient:
            with self.assertRaises(TransientAgentError):
                AnthropicCaller(client_with(error=error)).call(self.request())
        permanent = [
            status_error(anthropic.AuthenticationError, 401),
            status_error(anthropic.BadRequestError, 400),
            status_error(anthropic.NotFoundError, 404),
        ]
        for error in permanent:
            with self.assertRaises(AgentError) as ctx:
                AnthropicCaller(client_with(error=error)).call(self.request())
            self.assertNotIsInstance(ctx.exception, TransientAgentError)

    def test_missing_key(self):
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": ""}):
            with self.assertRaisesMessage(AgentError, "No Anthropic API key"):
                AnthropicCaller().call(self.request())

    def test_tool_loop_runs_client_tools_and_resumes_paused_turns(self):
        tool_use = SimpleNamespace(type="tool_use", id="tu_1", name="record_finding", input={"text": "Prices up 30%"})
        search = SimpleNamespace(type="server_tool_use", name="web_search", input={"query": "onion prices"})
        streams = [
            FakeStream(message(content=[search], stop_reason="pause_turn"),
                       [SimpleNamespace(type="content_block_stop", content_block=search)]),
            FakeStream(message(content=[tool_use], stop_reason="tool_use")),
            FakeStream(message(content=[SimpleNamespace(type="text", text="Done.")])),
        ]
        client = client_with(*streams)
        recorded, events = [], []
        response = AnthropicCaller(client).call(
            self.request(
                tools=[{"name": "record_finding"}],
                tool_handlers={"record_finding": lambda data: recorded.append(data) or "Saved as finding 1."},
                on_event=lambda kind, msg, data=None: events.append(msg),
            )
        )
        self.assertEqual(recorded, [{"text": "Prices up 30%"}])
        self.assertEqual(response.text, "Done.")
        self.assertEqual(response.usage.input_tokens, 3000)
        self.assertIn("Searching: onion prices", events)
        last_messages = client.beta.messages.stream.call_args.kwargs["messages"]
        self.assertEqual(last_messages[-1]["content"][0]["tool_use_id"], "tu_1")
        self.assertEqual(last_messages[-1]["content"][0]["content"], "Saved as finding 1.")

    def test_cost_estimate_uses_the_price_table_and_search_fee(self):
        usage = SimpleNamespace(
            input_tokens=1_000_000, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0, web_searches=10
        )
        self.assertEqual(estimate_cost("claude-opus-5-5", usage), Decimal("4.1"))
        self.assertEqual(estimate_cost("some-unknown-model", usage), Decimal("0.1"))

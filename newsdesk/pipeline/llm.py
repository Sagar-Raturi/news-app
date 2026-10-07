"""One call to one agent: the only place the pipeline talks to Claude.

`AnthropicCaller` streams the request (long outputs never hit HTTP timeouts,
and text deltas feed the live activity view), runs the tool loop for agents
with tools, and returns validated structured output plus usage. `get_caller()`
returns the scripted `FakeCaller` when NEWSDESK_WRITER=fake, so the whole
pipeline runs offline in demos and tests.
"""

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

import anthropic
from django.conf import settings
from pydantic import BaseModel, ValidationError

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOOL_TURNS = 30


class AgentError(Exception):
    """The step failed in a way retrying won't fix. The message is shown to editors."""


class TransientAgentError(AgentError):
    """Rate limits, overload, network trouble: worth retrying later."""


@dataclass
class AgentRequest:
    agent: Any  # AgentDefinition
    system: list
    messages: list
    output_format: type[BaseModel] | None = None
    tools: list = field(default_factory=list)
    # Client-side tools: name -> function(input dict) -> result string
    tool_handlers: dict[str, Callable[[dict], str]] = field(default_factory=dict)
    # Called with (kind, message, data) for the live activity feed
    on_event: Callable[..., None] | None = None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0

    def add(self, usage):
        if usage is None:
            return
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        server = getattr(usage, "server_tool_use", None)
        self.web_searches += getattr(server, "web_search_requests", 0) or 0


@dataclass
class AgentResponse:
    parsed: BaseModel | None
    text: str
    model: str
    usage: Usage = field(default_factory=Usage)
    # Every content block the agent produced, across tool turns (search results, fetches...)
    blocks: list = field(default_factory=list)


def estimate_cost(model, usage):
    """US$ estimate from the editable price table; zero for unknown models."""
    from newsdesk.models import ModelPrice, NewsroomAISettings

    price = ModelPrice.objects.filter(model=model).first()
    cost = Decimal(0)
    if price:
        cost += price.cost(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cache_read_tokens=usage.cache_read_tokens,
        )
    if usage.web_searches:
        cost += Decimal(usage.web_searches) * NewsroomAISettings.load().web_search_cost_per_1000 / 1000
    return cost


def _supports_effort(model):
    # Haiku 4.5 and older Sonnets reject output_config.effort.
    return not model.startswith(("claude-haiku", "claude-3", "claude-sonnet-4-5"))


def describe_tool_use(name, tool_input):
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if name == "web_search":
        return f"Searching: {tool_input.get('query', '')}".strip()
    if name == "web_fetch":
        return f"Reading: {tool_input.get('url', '')}".strip()
    return f"Using {name}"


def server_tools(agent):
    tools = []
    if agent.web_search:
        tools.append({"type": "web_search_20260209", "name": "web_search", "max_uses": agent.max_web_uses})
    if agent.web_fetch:
        tools.append({"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": agent.max_web_uses})
    return tools


class AnthropicCaller:
    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                raise AgentError(
                    "No Anthropic API key configured. Set ANTHROPIC_API_KEY (see README), "
                    "or NEWSDESK_WRITER=fake to try the flow offline."
                )
            self._client = anthropic.Anthropic(max_retries=3)
        return self._client

    def call(self, request):
        agent = request.agent
        params = {
            "model": agent.model,
            "max_tokens": agent.max_tokens,
            "system": request.system,
            "betas": [FALLBACK_BETA],
            # On a safety decline, retry on a suitable model inside the same call.
            "fallbacks": "default",
        }
        if _supports_effort(agent.model):
            params["output_config"] = {"effort": agent.effort}
        if request.output_format is not None:
            params["output_format"] = request.output_format
        tools = list(request.tools)
        if tools:
            params["tools"] = tools

        messages = list(request.messages)
        usage, blocks = Usage(), []
        final = None
        for _turn in range(MAX_TOOL_TURNS):
            final = self._stream(params, messages, request)
            usage.add(final.usage)
            blocks.extend(final.content)
            if final.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": final.content})
                continue
            if final.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": final.content})
                messages.append({"role": "user", "content": self._run_tools(final, request)})
                continue
            break
        else:
            raise AgentError("The agent kept calling tools without finishing.")

        if final.stop_reason == "refusal":
            raise AgentError("The model declined this task. Rework the brief or feedback and try again.")
        if final.stop_reason == "max_tokens":
            raise AgentError("The agent ran past its length limit. Raise its max tokens or narrow the task.")

        text = "".join(b.text for b in final.content if getattr(b, "type", "") == "text")
        parsed = None
        if request.output_format is not None:
            parsed = getattr(final, "parsed_output", None)
            if parsed is None:
                try:
                    parsed = request.output_format.model_validate_json(text)
                except ValidationError:
                    raise AgentError("The agent did not return usable output.")
        return AgentResponse(parsed=parsed, text=text, model=final.model or agent.model, usage=usage, blocks=blocks)

    def _stream(self, params, messages, request):
        emit = request.on_event or (lambda *a, **k: None)
        try:
            with self.client.beta.messages.stream(messages=messages, **params) as stream:
                for event in stream:
                    if event.type == "text":
                        emit("text", event.text)
                    elif event.type == "content_block_stop":
                        block = getattr(event, "content_block", None)
                        if getattr(block, "type", "") == "server_tool_use":
                            emit("tool", describe_tool_use(block.name, block.input), {"tool": block.name})
                return stream.get_final_message()
        except anthropic.AuthenticationError:
            raise AgentError("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY.")
        except anthropic.PermissionDeniedError as exc:
            raise AgentError(f"The API key may not use this model or feature: {exc.message}")
        except anthropic.NotFoundError:
            raise AgentError(f"Unknown model '{params['model']}'. Check the agent's model in the admin.")
        except anthropic.BadRequestError as exc:
            raise AgentError(f"The Anthropic API rejected the request: {exc.message}")
        except anthropic.RateLimitError:
            raise TransientAgentError("Rate limited by the Anthropic API.")
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientAgentError(f"The Anthropic API is having trouble ({exc.status_code}).")
            raise AgentError(f"Anthropic API error ({exc.status_code}).")
        except anthropic.APIConnectionError:
            raise TransientAgentError("Could not reach the Anthropic API (network error).")

    def _run_tools(self, message, request):
        results = []
        for block in message.content:
            if getattr(block, "type", "") != "tool_use":
                continue
            handler = request.tool_handlers.get(block.name)
            if handler is None:
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": "Unknown tool.", "is_error": True}
                )
                continue
            try:
                output = handler(block.input if isinstance(block.input, dict) else json.loads(block.input))
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
            except (ValueError, KeyError, TypeError) as exc:
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(exc), "is_error": True})
        return results


def get_caller():
    if settings.NEWSDESK_WRITER == "fake":
        from .fake import FakeCaller

        return FakeCaller()
    return AnthropicCaller()

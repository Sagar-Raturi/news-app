"""Offline stand-ins for Claude.

FakeCaller (NEWSDESK_WRITER=fake) produces plausible, clearly-labelled demo
output for every role without calling any API. ScriptedCaller is for tests:
it returns queued responses per role and records every request it receives.
"""

import re

from newsdesk.schema import DraftBlock

from .llm import AgentResponse, Usage
from .schemas import FullDraft


def _block(type, text="", detail="", points=None, source=""):
    return DraftBlock(type=type, text=text, detail=detail, points=points or [], source=source)


def _user_text(request):
    content = request.messages[-1]["content"]
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content


def _tag(text, name):
    match = re.search(rf"<{name}>\n?(.*?)\n?</{name}>", text, re.S)
    return match.group(1).strip() if match else ""


class FakeCaller:
    """Deterministic demo output, so the whole flow can be tried without an API key."""

    def call(self, request):
        role = request.agent.role
        handler = getattr(self, role, None)
        if handler is None:
            raise NotImplementedError(f"The fake caller has no output for the {role} agent.")
        if request.on_event:
            request.on_event("progress", f"[demo] The {request.agent.name.lower()} is working (no API call).")
        parsed = handler(request, _user_text(request))
        return AgentResponse(parsed=parsed, text="", model="fake", usage=Usage())

    def writer(self, request, text):
        brief_text = _tag(text, "brief")
        brief = next((line[7:] for line in brief_text.splitlines() if line.startswith("Brief: ")), "the brief")
        topic = next((line[7:] for line in brief_text.splitlines() if line.startswith("Topic: ")), "Demo article")
        cite = " [S1]" if "[S1]" in _tag(text, "sources") else ""
        return FullDraft(
            headline=f"{topic} (demo draft)"[:90],
            standfirst="A placeholder draft written without calling the AI model, to show how the workspace works.",
            body=[
                _block(
                    "paragraph",
                    "This draft was produced offline (NEWSDESK_WRITER=fake), so it contains no real reporting. "
                    f"It shows where the agents' article appears and how revisions and versions work{cite}.",
                ),
                _block("heading", "What the editor asked for"),
                _block("paragraph", brief),
                _block(
                    "key_points",
                    "How this demo works",
                    points=["No API calls, no cost", "Every step is logged", "Nothing is published without approval"],
                ),
            ],
            tags=["Demo"],
            notes="Demo draft: switch NEWSDESK_WRITER to anthropic for real research and writing.",
        )


class ScriptedCaller:
    """Test double: queued responses per role; records requests.

    Each queued item is an AgentResponse, a pydantic object (wrapped with zero
    usage), an exception instance (raised), or a callable taking the request.
    """

    def __init__(self, script=None, usage=None):
        self.script = {role: list(items) for role, items in (script or {}).items()}
        self.requests = []
        self.usage = usage

    def add(self, role, *items):
        self.script.setdefault(role, []).extend(items)

    def call(self, request):
        self.requests.append(request)
        role = request.agent.role
        if not self.script.get(role):
            raise AssertionError(f"No scripted response left for the {role} agent")
        item = self.script[role].pop(0)
        if callable(item) and not isinstance(item, type):
            item = item(request)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, AgentResponse):
            return item
        usage = Usage(**self.usage) if self.usage else Usage()
        return AgentResponse(parsed=item, text="", model=request.agent.model, usage=usage)

    def roles(self):
        return [r.agent.role for r in self.requests]

"""Offline stand-ins for Claude.

FakeCaller (NEWSDESK_WRITER=fake) produces plausible, clearly-labelled demo
output for every role without calling any API. ScriptedCaller is for tests:
it returns queued responses per role and records every request it receives.
"""

import re
import time
from types import SimpleNamespace

from django.conf import settings

from newsdesk.schema import DraftBlock

from .llm import AgentResponse, Usage
from .planning import FIRST_DRAFT
from .schemas import (
    Analysis,
    BlockEdit,
    Edits,
    FactCheck,
    Flag,
    FullDraft,
    Outline,
    OutlineSection,
    Perspective,
    Plan,
    PlanStep,
    Seo,
)


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
    """Deterministic demo output for every agent, so the whole flow can be tried without an API key.

    Everything it writes is labelled as a demo. The fake researcher records
    findings against example.org pages (or the editor's own links), which it
    also reports as "search results", so the pipeline's link checks pass.
    """

    def call(self, request):
        role = request.agent.role
        handler = getattr(self, role, None)
        if handler is None:
            raise NotImplementedError(f"The fake caller has no output for the {role} agent.")
        if request.on_event:
            request.on_event("progress", f"[demo] The {request.agent.name.lower()} is working (no API call).")
        result = handler(request, _user_text(request))
        response = result if isinstance(result, AgentResponse) else AgentResponse(parsed=result, text="", model="fake")
        if response.parsed is not None:
            self.stream(request, response.parsed)
        return response

    def stream(self, request, parsed):
        """Play the output back word by word, so the live feed has something to show in demos."""
        delay = settings.NEWSDESK_FAKE_DELAY
        if not request.on_event or delay <= 0:
            return
        words = readable(parsed).split(" ")
        for i in range(0, len(words), 4):
            request.on_event("text", " ".join(words[i : i + 4]) + " ")
            time.sleep(delay)

    # -- roles --------------------------------------------------------------------

    def orchestrator(self, request, text):
        if "Plan the first draft" in text or "completely new draft" in text:
            steps = [PlanStep(task=task, instructions=f"[demo] {instructions}", blocks=[]) for task, instructions in FIRST_DRAFT]
            message = "[demo] Researching, analysing, outlining, writing, editing and fact-checking a first draft."
        else:
            feedback = _tag(text, "editor_feedback") or "the editor's notes"
            steps = [PlanStep(task="revise", instructions=f"[demo] Address: {feedback}", blocks=["B1"])]
            message = "[demo] The writer will revise the opening to address your feedback."
        return Plan(message_to_editor=message, steps=steps)

    def researcher(self, request, text):
        topic = _brief_field(text, "Topic") or "the topic"
        editor_links = re.findall(r"<(https?://[^>\s]+)>", _tag(text, "sources"))
        urls = editor_links[:1] + [f"https://example.org/ledger-demo/{n}" for n in (1, 2)]
        findings = [
            ("background", f"[demo] Background on {topic} would appear here.", "Demo detail from a source."),
            ("figure", "[demo] A key figure with its period and source.", "e.g. 12% year on year (demo)"),
            ("perspective", "[demo] The strongest counter-argument would be summarised here.", ""),
        ]
        record = request.tool_handlers.get("record_finding")
        for (kind, finding, detail), url in zip(findings, urls):
            if request.on_event:
                request.on_event("tool", f"Searching: {topic} ({kind}) [demo]", {"tool": "web_search"})
            if record:
                record({"kind": kind, "text": finding, "detail": detail, "url": url,
                        "title": f"Demo source for {topic}", "publisher": "Example (demo)"})
        results = [SimpleNamespace(type="web_search_result", url=url, title="Demo result") for url in urls]
        return AgentResponse(
            parsed=None,
            text="[demo] Research notes: no real searching was done (NEWSDESK_WRITER=fake).",
            model="fake",
            blocks=[SimpleNamespace(type="web_search_tool_result", content=results)],
        )

    def analyst(self, request, text):
        topic = _brief_field(text, "Topic") or "the topic"
        return Analysis(
            thesis=f"[demo] The central argument about {topic} would go here [S1].",
            context="[demo] Why this matters now, with sources [S1].",
            perspectives=[
                Perspective(view="[demo] The main view", evidence="[demo] Evidence [S1]"),
                Perspective(view="[demo] The strongest counter-view", evidence="[demo] Evidence [S2]"),
            ],
            implications="[demo] Who gains, who loses, what to watch.",
            uncertainties="[demo] What the evidence can't tell us yet.",
        )

    def outliner(self, request, text):
        topic = _brief_field(text, "Topic") or "Demo article"
        return Outline(
            headline_options=[f"{topic} (demo draft)", f"What {topic} means (demo)"],
            standfirst="[demo] The argument in one sentence.",
            sections=[
                OutlineSection(heading="", points=["[demo] Opening: what's happening and why it matters"], words=150),
                OutlineSection(heading="What the editor asked for", points=["[demo] The brief"], words=150),
            ],
            extras=["[demo] A key points box"],
        )

    def writer(self, request, text):
        if "Return only the edits" in text:
            return self._demo_edits(text, "writer")
        brief = _brief_field(text, "Brief") or "the brief"
        topic = _brief_field(text, "Topic") or "Demo article"
        sources = _tag(text, "sources")
        cite = " [S1]" if "[S1]" in sources else ""
        cite2 = " [S2]" if "[S2]" in sources else ""
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
                _block("paragraph", f"{brief}{cite2}"),
                _block(
                    "key_points",
                    "How this demo works",
                    points=["No API calls, no cost", "Every step is logged", "Nothing is published without approval"],
                ),
            ],
            tags=["Demo"],
            notes="Demo draft: switch NEWSDESK_WRITER to anthropic for real research and writing.",
        )

    def editor(self, request, text):
        return self._demo_edits(text, "editor")

    def _demo_edits(self, text, role):
        """Demo revisions: the writer lightly rewrites the first targeted block so the diff shows a change."""
        targets = re.search(r"Blocks to work on: ([B0-9, ]+)\.", text)
        ref = targets.group(1).split(",")[0].strip() if targets else "B1"
        current = re.search(rf"\[{ref}\] \(paragraph\) (.+)", text)
        if role == "editor" or not current:
            return Edits(edits=[], headline="", standfirst="", notes=f"[demo] The {role} found nothing to change.")
        new_text = f"{current.group(1).strip()} [demo revision]"
        return Edits(
            edits=[BlockEdit(op="replace", block=ref, new_block=_block("paragraph", new_text))],
            headline="",
            standfirst="",
            notes=f"[demo] Revised {ref} to address the feedback.",
        )

    def fact_checker(self, request, text):
        match = re.search(r"\[B1\] \(paragraph\) ([^.\n]+)", text)
        flags = []
        if match:
            flags.append(
                Flag(block="B1", claim=match.group(1).strip()[:200], severity="low",
                     issue="[demo] No real checking was done in demo mode.",
                     suggestion="Check this against the sources before publishing.", sources=[])
            )
        return FactCheck(summary="[demo] Fact-check simulated; nothing was verified.", flags=flags)

    def seo(self, request, text):
        headline = re.search(r"Headline: (.+)", text)
        headline = headline.group(1).strip() if headline else "Demo article"
        slug = re.sub(r"[^a-z0-9]+", "-", headline.lower()).strip("-")[:60]
        return Seo(
            headline_options=[headline, f"{headline}: what it means"],
            headline=headline,
            meta_description="[demo] A one-line description for search results.",
            slug=slug,
            tags=["Demo"],
        )


def _brief_field(text, name):
    for line in _tag(text, "brief").splitlines():
        if line.startswith(f"{name}: "):
            return line[len(name) + 2 :].strip()
    return ""


def readable(parsed):
    """Plain text of a structured output, for the demo stream."""
    if isinstance(parsed, FullDraft):
        parts = [parsed.headline, parsed.standfirst]
        for block in parsed.body:
            parts += [block.text, block.detail, *block.points]
        return " ".join(p for p in parts if p)
    return parsed.model_dump_json()


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

"""Writers turn a DraftRequest into an ArticleDraft.

AnthropicWriter calls Claude; FakeWriter returns a canned draft built from the
brief so the whole flow can be demoed and tested without an API key.
Choose with settings.NEWSDESK_WRITER ("anthropic" or "fake").
"""

import os
from dataclasses import dataclass

import anthropic
from django.conf import settings

from .prompts import build_system, build_user_message
from .schema import ArticleDraft, DraftBlock, DraftSource

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class DraftError(Exception):
    """A draft could not be produced; the message is shown to editors."""


@dataclass
class DraftResult:
    draft: ArticleDraft
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


class AnthropicWriter:
    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def write(self, request):
        desk = request.desk
        if self._client is None and not (
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        ):
            raise DraftError(
                "No Anthropic API key configured. Set ANTHROPIC_API_KEY (see README), "
                "or NEWSDESK_WRITER=fake to try the flow with canned drafts."
            )
        try:
            response = self.client.beta.messages.parse(
                model=desk.model,
                max_tokens=settings.NEWSDESK_MAX_TOKENS,
                system=build_system(desk, request.article_type),
                messages=[{"role": "user", "content": build_user_message(request)}],
                output_format=ArticleDraft,
                output_config={"effort": desk.effort},
                # If a safety classifier declines, retry on a suitable model
                # inside the same call instead of failing outright.
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            raise DraftError("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY.")
        except anthropic.RateLimitError:
            raise DraftError("Rate limited by the Anthropic API. Try again in a few minutes.")
        except anthropic.BadRequestError as exc:
            raise DraftError(f"The Anthropic API rejected the request: {exc.message}")
        except anthropic.APIStatusError as exc:
            raise DraftError(f"Anthropic API error ({exc.status_code}). Try again later.")
        except anthropic.APIConnectionError:
            raise DraftError("Could not reach the Anthropic API (network error).")

        if response.stop_reason == "refusal":
            raise DraftError("The model declined to write this draft. Rework the brief or material.")
        if response.stop_reason == "max_tokens":
            raise DraftError("The draft ran past the length limit. Narrow the brief or trim the material.")
        draft = response.parsed_output
        if draft is None:
            raise DraftError("The model did not return a usable draft.")

        usage = response.usage
        return DraftResult(
            draft=draft,
            model=response.model,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )


class FakeWriter:
    """Deterministic offline draft for demos and tests. Never calls an API."""

    def write(self, request):
        brief = " ".join(request.brief.split())
        headline = brief.split(".")[0][:90] or "Untitled draft"
        draft = ArticleDraft(
            headline=headline,
            standfirst=f"[Demo draft from the {request.desk.name}] {brief[:200]}",
            body=[
                DraftBlock(
                    type="paragraph",
                    text="This is a placeholder draft produced without calling the AI model "
                    "(NEWSDESK_WRITER=fake). It shows where an agent-written article lands "
                    "and how it moves through Editor review.",
                    detail="",
                    points=[],
                    source="",
                ),
                DraftBlock(type="heading", text="The brief", detail="", points=[], source=""),
                DraftBlock(type="paragraph", text=brief, detail="", points=[], source=""),
                DraftBlock(
                    type="key_points",
                    text="What the agent was given",
                    detail="",
                    points=[
                        f"Desk: {request.desk.name}",
                        f"Article type: {request.get_article_type_display()}",
                        f"Feedback notes in memory: {len(request.desk.memory(request.article_type))}",
                    ],
                    source="",
                ),
            ],
            sources=[DraftSource(title="Material supplied by the editor", publisher="The Ledger", url="")],
            tags=["Demo"],
            editor_notes="Demo draft: replace with real reporting before publishing.",
        )
        return DraftResult(draft=draft, model="fake")


def get_writer():
    if settings.NEWSDESK_WRITER == "fake":
        return FakeWriter()
    return AnthropicWriter()

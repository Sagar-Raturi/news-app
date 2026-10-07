"""Structured outputs the agents return (validated by the SDK)."""

from pydantic import BaseModel, Field

from newsdesk.schema import DraftBlock


class FullDraft(BaseModel):
    """A complete article: first draft or full rewrite."""

    headline: str = Field(description="Under 90 characters, specific, no clickbait")
    standfirst: str = Field(description="One or two sentences stating the argument, under 280 characters")
    body: list[DraftBlock] = Field(description="The article body. Must start with a paragraph block.")
    tags: list[str] = Field(description="2-4 topic tags in Title Case")
    notes: str = Field(
        description="For the editor: what you could not support from the material, gaps, anything to check. "
        "Empty only if there is nothing to flag."
    )

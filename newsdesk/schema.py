"""Structured output the desk agents must return (validated by the SDK)."""

from typing import Literal

from pydantic import BaseModel, Field

BlockType = Literal["paragraph", "heading", "pullquote", "key_points", "qa", "stat", "callout"]


class DraftBlock(BaseModel):
    """One body block. Unused fields are empty strings / empty lists."""

    type: BlockType
    text: str = Field(
        description="paragraph: one paragraph of plain text. heading: the subheading. "
        "pullquote: the quoted words. qa: the question. stat: the figure (e.g. '6.5%'). "
        "callout and key_points: the box title."
    )
    detail: str = Field(
        description="qa: the answer. callout: the box text. stat: what the figure measures. "
        "pullquote: who said it (a role, never an invented name). Otherwise empty."
    )
    points: list[str] = Field(description="key_points only: 3-5 short points. Otherwise empty.")
    source: str = Field(description="stat only: where the figure comes from. Otherwise empty.")


class DraftSource(BaseModel):
    title: str
    publisher: str
    url: str = Field(description="Only a URL that appears in the source material, otherwise empty")


class ArticleDraft(BaseModel):
    headline: str = Field(description="Under 100 characters, no clickbait")
    standfirst: str = Field(description="One or two sentences, under 280 characters")
    body: list[DraftBlock] = Field(description="Must start with a paragraph block")
    sources: list[DraftSource]
    tags: list[str] = Field(description="2-4 topic tags in Title Case")
    editor_notes: str = Field(
        description="For the reviewing editor: claims that need checking, gaps in the "
        "material, anything you could not verify. Empty only if there is nothing to flag."
    )

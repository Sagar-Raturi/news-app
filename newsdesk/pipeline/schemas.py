"""Structured outputs the agents return (validated by the SDK).

Every field is required (structured outputs work best that way); "empty"
means an empty string or list. Block references are the B1, B2... labels the
agents see in the draft (see context.draft_block).
"""

from typing import Literal

from pydantic import BaseModel, Field

from newsdesk.schema import DraftBlock

Task = Literal["research", "analyse", "outline", "write", "revise", "edit", "seo"]


class PlanStep(BaseModel):
    task: Task
    instructions: str = Field(description="Exactly what this agent should do, and what to leave alone")
    blocks: list[str] = Field(description="Block references (e.g. B3) this step should change; empty for the whole article")


class Plan(BaseModel):
    """The orchestrator's plan. Fact-checking is added automatically after any change to the text."""

    message_to_editor: str = Field(description="One to three plain sentences telling the editor what will happen")
    steps: list[PlanStep]


class Perspective(BaseModel):
    view: str
    evidence: str = Field(description="The supporting evidence, with source markers like [S2]")


class Analysis(BaseModel):
    thesis: str = Field(description="The article's central claim, one or two sentences")
    context: str = Field(description="Why this matters now and how we got here, with source markers")
    perspectives: list[Perspective] = Field(description="At least two serious views, including the strongest counter-argument")
    implications: str = Field(description="Who gains, who loses, what happens next, what to watch")
    uncertainties: str = Field(description="What the evidence can't tell us yet")


class OutlineSection(BaseModel):
    heading: str = Field(description="Subheading, or empty for the opening section")
    points: list[str] = Field(description="Points this section must make, with source markers")
    words: int = Field(description="Rough word budget")


class Outline(BaseModel):
    headline_options: list[str]
    standfirst: str
    sections: list[OutlineSection]
    extras: list[str] = Field(description="Suggested key points box, key figure, fact box or pull quote; empty if none")


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


class BlockEdit(BaseModel):
    op: Literal["replace", "insert_after", "delete"]
    block: str = Field(description="The block reference, e.g. B4. For insert_after, B0 means at the very start.")
    new_block: DraftBlock = Field(description="The new or replacement block; ignored for delete")


class Edits(BaseModel):
    """Targeted changes to specific blocks. Blocks not mentioned stay exactly as they are."""

    edits: list[BlockEdit]
    headline: str = Field(description="New headline, or empty to keep it")
    standfirst: str = Field(description="New standfirst, or empty to keep it")
    notes: str = Field(description="What you changed and why, briefly; anything you couldn't do")


class Flag(BaseModel):
    block: str = Field(description="Block reference where the claim appears, e.g. B3; empty for headline/standfirst")
    claim: str = Field(description="The claim exactly as it appears in the draft")
    severity: Literal["high", "medium", "low"]
    issue: str
    suggestion: str
    sources: list[int] = Field(description="Numbers of the sources that bear on the claim (S3 -> 3)")


class FactCheck(BaseModel):
    summary: str = Field(description="One or two sentences on the draft's accuracy overall")
    flags: list[Flag]


class Seo(BaseModel):
    headline_options: list[str]
    headline: str = Field(description="The recommended headline, under 90 characters")
    meta_description: str = Field(description="Under 155 characters")
    slug: str = Field(description="lowercase-words-with-hyphens")
    tags: list[str] = Field(description="2-4 topic tags in Title Case")


RECORD_FINDING_TOOL = {
    "name": "record_finding",
    "description": "Save one research finding with the source it came from. Call it once per finding, as you go. "
    "Only record what you read in a source during this task.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["fact", "figure", "quote", "background", "perspective"]},
            "text": {"type": "string", "description": "The finding in your own words"},
            "detail": {"type": "string", "description": "Exact figure, quotation or context from the source; may be empty"},
            "url": {"type": "string", "description": "The URL of the page it came from"},
            "title": {"type": "string", "description": "The page or document title"},
            "publisher": {"type": "string", "description": "Who published it"},
        },
        "required": ["kind", "text", "detail", "url", "title", "publisher"],
        "additionalProperties": False,
    },
}

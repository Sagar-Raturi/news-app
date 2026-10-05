"""Builds each desk agent's prompt: house rules + desk style guide + desk memory.

The system prompt is split into two cached blocks. The house rules are the
same for every desk; the desk block changes only when an editor edits the
style guide or the desk's memory, so repeated drafts from a desk reuse the
cache.
"""

from news.models import ArticlePage

TYPE_GUIDANCE = {
    "news": "A news report of 350-500 words. Lead with what happened and why it matters. "
    "Mostly paragraphs; at most one pull quote. No opinion.",
    "analysis": "An analysis of 700-950 words. Explain causes, consequences and trade-offs, "
    "with 2-4 subheadings and at least one key_points, stat or pullquote block. Reasoned "
    "judgement is welcome; partisanship is not.",
    "explainer": "An explainer of 650-900 words built mainly from qa blocks (5-8 questions a "
    "curious reader would ask), opening with a short paragraph and ending with a callout "
    "titled 'What happens next' where the material supports it.",
}

HOUSE_RULES = """You are a staff writer at The Ledger, an analysis-led Indian news publication in the spirit of The Hindu and The Economist. You write for an intelligent general reader in clear, sober British/Indian English (programme, labour; lakh and crore where natural). No clichés, no hype, no rhetorical questions in headlines.

Accuracy rules (these override everything else):
- Use only facts, figures and quotations found in the source material the editor provides. Never invent facts, numbers, dates, names, quotes or sources.
- Never put words in the mouth of a real, named person unless the exact quote is in the source material. Attribute paraphrased claims to the source they come from.
- If the material is thin or contradictory, write a shorter piece and say what is missing in editor_notes. Do not fill gaps from memory.
- Hedge anything the material itself hedges. Distinguish what is known from what is claimed.
- Sources: list the documents you relied on. Use a URL only if it appears verbatim in the source material; otherwise leave url empty.

Format rules:
- Return the draft in the required structure. The body must start with a paragraph block.
- Paragraph blocks hold one paragraph of plain text each: no HTML, no Markdown.
- Do not write opinion columns or editorials, and do not take sides on contested political questions.
- An editor reviews every draft before publication and is accountable for it; flag anything they should check in editor_notes."""


def desk_block(desk, article_type):
    lines = [
        f"You are writing for the {desk.name} ({desk.section.title} section).",
        "",
        "Desk style guide:",
        desk.style_guide.strip(),
    ]
    notes = desk.memory(article_type)
    if notes:
        type_label = dict(ArticlePage.ArticleType.choices).get(article_type, article_type)
        lines += [
            "",
            f"Feedback from this desk's editors (apply all of it; later notes win if they conflict). "
            f"Notes marked [{type_label}] apply to this article type specifically:",
        ]
        for note in notes:
            prefix = f"[{note.get_article_type_display()}] " if note.article_type else ""
            lines.append(f"- {prefix}{note.note.strip()}")
    return "\n".join(lines)


def build_system(desk, article_type):
    """System prompt blocks with cache breakpoints after each stable part."""
    return [
        {"type": "text", "text": HOUSE_RULES, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": desk_block(desk, article_type), "cache_control": {"type": "ephemeral"}},
    ]


def build_user_message(request):
    label = request.get_article_type_display()
    return (
        f"Write a {label.lower()}.\n\n"
        f"Article type guidance: {TYPE_GUIDANCE.get(request.article_type, '')}\n\n"
        f"<brief>\n{request.brief.strip()}\n</brief>\n\n"
        f"<source_material>\n{request.source_material.strip()}\n</source_material>"
    )

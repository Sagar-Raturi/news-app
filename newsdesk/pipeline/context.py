"""Build each agent's prompt from one article's session, and nothing else.

Every query here is scoped to a single workspace: that is what keeps one
article's brief, drafts, feedback and research out of another's prompts.
The system prompt is the agent's role prompt, then the house style and the
section's guidelines (both cached: they rarely change); everything about the
article goes in the user message.
"""

from news.models import ArticlePage
from newsdesk.content import TEXT_BLOCK_TYPES, block_text
from newsdesk.models import NewsroomAISettings, Source
from newsdesk.prompts import TYPE_GUIDANCE
from newsdesk.roles import STYLE_ROLES


def _cached(text):
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


def section_guidelines(workspace):
    desk = workspace.desk
    lines = [f"Section: {desk.section.title} ({desk.name}).", "", "Section guidelines:", desk.style_guide.strip()]
    notes = desk.memory(workspace.article_type)
    if notes:
        lines += ["", "Standing feedback from this section's editors (later notes win if they conflict):"]
        for note in notes:
            prefix = f"[{note.get_article_type_display()} only] " if note.article_type else ""
            lines.append(f"- {prefix}{note.note.strip()}")
    return "\n".join(lines)


def build_system(agent, workspace):
    blocks = [_cached(agent.system_prompt.strip())]
    if agent.role in STYLE_ROLES:
        house_style = NewsroomAISettings.load().house_style.strip()
        blocks.append(_cached(f"House style:\n{house_style}\n\n{section_guidelines(workspace)}"))
    return blocks


def target_length(workspace):
    if workspace.target_words:
        return f"About {workspace.target_words} words."
    return TYPE_GUIDANCE.get(workspace.article_type, "")


def brief_block(workspace):
    label = dict(ArticlePage.ArticleType.choices).get(workspace.article_type, workspace.article_type)
    fields = [
        ("Topic", workspace.topic.title),
        ("Type", label),
        ("Brief", workspace.brief),
        ("Length", target_length(workspace)),
        ("Angle / viewpoint", workspace.angle),
        ("Tone", workspace.tone),
        ("Audience", workspace.audience),
        ("Must include", workspace.must_include),
        ("Sources to avoid", workspace.sources_to_avoid),
    ]
    lines = [f"{name}: {value.strip()}" for name, value in fields if value and value.strip()]
    return "<brief>\n" + "\n".join(lines) + "\n</brief>"


def record_editor_sources(workspace):
    """Turn the brief's 'sources to use' into numbered sources (links one by one, other text as one)."""
    links, other = [], []
    for line in workspace.sources_to_use.splitlines():
        line = line.strip()
        if not line:
            continue
        url = next((w for w in line.split() if w.startswith(("http://", "https://"))), "")
        if url:
            title = line.replace(url, "").strip(" -–—:") or url
            links.append(Source.record(workspace, url=url, title=title, origin=Source.Origin.EDITOR))
        else:
            other.append(line)
    if other:
        material = "\n".join(other)
        existing = workspace.sources.filter(origin=Source.Origin.EDITOR, url="").first()
        if existing:
            existing.excerpt = material
            existing.save(update_fields=["excerpt"])
        else:
            Source.record(
                workspace, title="Material supplied by the editor", origin=Source.Origin.EDITOR, excerpt=material
            )
    return links


def sources_block(workspace, with_findings=True):
    sources = list(workspace.sources.prefetch_related("findings"))
    if not sources:
        return "<sources>\nNo sources yet.\n</sources>"
    parts = []
    for source in sources:
        head = f"[S{source.number}] {source.title}"
        if source.publisher:
            head += f", {source.publisher}"
        if source.url:
            head += f" <{source.url}>"
        lines = [head]
        if source.excerpt:
            lines.append(source.excerpt.strip())
        if with_findings:
            for finding in source.findings.all():
                detail = f" ({finding.detail.strip()})" if finding.detail.strip() else ""
                lines.append(f"- {finding.get_kind_display()}: {finding.text.strip()}{detail}")
        parts.append("\n".join(lines))
    return "<sources>\n" + "\n\n".join(parts) + "\n</sources>"


def block_refs(draft):
    """B1, B2... for each block, so agents can point at passages without long ids."""
    return {f"B{i}": block["id"] for i, block in enumerate(draft["body"], start=1)}


def draft_block(draft, tag="current_draft"):
    lines = [f"Headline: {draft['headline']}", f"Standfirst: {draft['dek']}", ""]
    for ref, block in zip(block_refs(draft), draft["body"]):
        if block["type"] in TEXT_BLOCK_TYPES:
            lines.append(f"[{ref}] ({block['type']}) {block_text(block)}")
        else:
            lines.append(f"[{ref}] ({block['type']}: not editable by agents)")
    if draft.get("tags"):
        lines.append("")
        lines.append(f"Tags: {', '.join(draft['tags'])}")
    return f"<{tag}>\n" + "\n".join(lines) + f"\n</{tag}>"

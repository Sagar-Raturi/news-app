"""Render a version's blocks for the workspace (admin) view.

Each block is wrapped with its id so inline comments can anchor to it, and
source markers like [S3] become links to the source list. Paragraph HTML is
either escaped agent text or Wagtail rich text, so it is safe to render.
"""

import re

from django.utils.html import escape, format_html, format_html_join
from django.utils.safestring import mark_safe
from wagtail.rich_text import expand_db_html

from .content import list_items

CITATION = re.compile(r"\[S(\d+)\]")
BLOCK_LABELS = {"image": "Image", "embed": "Embed", "table": "Table"}


def cite(html, known):
    """Turn [S3] markers into superscript links; unknown numbers are highlighted."""

    def link(match):
        number = int(match.group(1))
        if number in known:
            return f'<sup class="nd-cite"><a href="#source-{number}" title="Source {number}">{number}</a></sup>'
        return f'<sup class="nd-cite nd-cite--missing" title="No source {number} in this article">S{number}?</sup>'

    return mark_safe(CITATION.sub(link, str(html)))


def _rich(html):
    return expand_db_html(html or "")


def block_html(block, known):
    kind, value = block.get("type"), block.get("value")
    if kind == "paragraph":
        return cite(_rich(value), known)
    if kind == "heading":
        return format_html("<h2>{}</h2>", cite(escape(value), known))
    if kind == "pullquote":
        return format_html(
            '<blockquote class="nd-pullquote"><p>{}</p><footer>{}</footer></blockquote>',
            cite(escape(value.get("quote", "")), known),
            value.get("attribution", ""),
        )
    if kind == "key_points":
        items = format_html_join("", "<li>{}</li>", ((cite(escape(p), known),) for p in list_items(value.get("points"))))
        return format_html('<aside class="nd-box"><h3>{}</h3><ul>{}</ul></aside>', value.get("title", ""), items)
    if kind == "qa":
        return format_html(
            '<div class="nd-qa"><h3>{}</h3>{}</div>', value.get("question", ""), cite(_rich(value.get("answer")), known)
        )
    if kind == "stat":
        source = format_html("<small>Source: {}</small>", value["source"]) if value.get("source") else ""
        return format_html(
            '<aside class="nd-stat"><strong>{}</strong><span>{}</span>{}</aside>',
            value.get("figure", ""),
            cite(escape(value.get("label", "")), known),
            source,
        )
    if kind == "callout":
        return format_html(
            '<aside class="nd-box"><h3>{}</h3>{}</aside>', value.get("title", ""), cite(_rich(value.get("body")), known)
        )
    label = BLOCK_LABELS.get(kind, kind or "Block")
    return format_html('<p class="nd-placeholder">{} — edit it in the page editor</p>', label)


def render_version(version):
    sources = version.workspace.sources.all()
    known = {s.number for s in sources}
    return {
        "headline": cite(escape(version.headline), known),
        "dek": cite(escape(version.dek), known),
        "blocks": [{"id": b.get("id", ""), "type": b.get("type"), "html": block_html(b, known)} for b in version.body],
        "sources": version.sources(),
    }

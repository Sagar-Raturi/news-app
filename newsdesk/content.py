"""Helpers for article bodies stored as raw StreamField data.

An ArticleVersion keeps its body in the same JSON shape as ArticlePage.body
(a list of {"type", "value", "id"}), so versions convert to page revisions and
back without loss. Block ids are stable across versions: an agent's revision
replaces only the blocks it changes, so inline comments on untouched blocks
keep their anchors.
"""

import re
import uuid
from html import unescape

from django.utils.html import strip_tags

# Blocks the agents can read and write. Others (images, embeds, tables) are
# kept as they are and shown to agents as placeholders.
TEXT_BLOCK_TYPES = {"paragraph", "heading", "pullquote", "key_points", "qa", "stat", "callout"}

_BLOCK_BREAKS = re.compile(r"</(p|li|h[1-6])>|<br\s*/?>", re.IGNORECASE)


def new_block_id():
    return str(uuid.uuid4())


def ensure_ids(body):
    """Give every block an id (Wagtail does the same when saving)."""
    for block in body:
        if not block.get("id"):
            block["id"] = new_block_id()
    return body


def html_to_text(html):
    """Rich text HTML -> plain text, one blank line between paragraphs."""
    html = _BLOCK_BREAKS.sub(lambda m: m.group(0) + "\n\n", html or "")
    paragraphs = (" ".join(unescape(chunk).split()) for chunk in strip_tags(html).split("\n\n"))
    return "\n\n".join(p for p in paragraphs if p)


def block_text(block):
    """The readable text of one block: what inline comments anchor to."""
    kind, value = block.get("type"), block.get("value")
    if kind == "paragraph":
        return html_to_text(value)
    if kind == "heading":
        return " ".join(str(value or "").split())
    if kind == "pullquote":
        return " ".join(f"{value.get('quote', '')} — {value.get('attribution', '')}".split()).rstrip(" —")
    if kind == "key_points":
        return "\n".join([value.get("title", "")] + [f"• {p}" for p in value.get("points", [])])
    if kind == "qa":
        return f"{value.get('question', '')}\n\n{html_to_text(value.get('answer', ''))}"
    if kind == "stat":
        source = f" (source: {value['source']})" if value.get("source") else ""
        return f"{value.get('figure', '')} — {value.get('label', '')}{source}"
    if kind == "callout":
        return f"{value.get('title', '')}\n\n{html_to_text(value.get('body', ''))}"
    return ""


def body_text(body):
    return "\n\n".join(text for text in (block_text(b) for b in body) if text)


def word_count(body):
    return len(body_text(body).split())

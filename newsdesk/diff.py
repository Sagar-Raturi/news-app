"""Compare two versions block by block, with word-level changes inside a block.

Blocks are matched by their stable ids, so a revision that rewrote one
paragraph shows exactly that paragraph as changed.
"""

import re
from difflib import SequenceMatcher

from django.utils.html import escape
from django.utils.safestring import mark_safe

from .content import block_text

_TOKENS = re.compile(r"\s+|[^\s]+")


def word_diff(old, new):
    """HTML with <del>/<ins> marking word changes between two strings."""
    a, b = _TOKENS.findall(old), _TOKENS.findall(new)
    out = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(escape("".join(a[i1:i2])))
            continue
        if op in ("delete", "replace"):
            out.append(f"<del>{escape(''.join(a[i1:i2]))}</del>")
        if op in ("insert", "replace"):
            out.append(f"<ins>{escape(''.join(b[j1:j2]))}</ins>")
    return mark_safe("".join(out).replace("\n", "<br>"))


def _text_row(label, old, new):
    return {"label": label, "changed": old != new, "html": word_diff(old, new)}


def diff_versions(old, new):
    """Rows describing how `new` differs from `old`."""
    old_blocks = {b["id"]: b for b in old.body}
    new_blocks = {b["id"]: b for b in new.body}
    old_ids, new_ids = [b["id"] for b in old.body], [b["id"] for b in new.body]

    rows = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, old_ids, new_ids, autojunk=False).get_opcodes():
        if op == "equal":
            for block_id in new_ids[j1:j2]:
                before, after = block_text(old_blocks[block_id]), block_text(new_blocks[block_id])
                status = "same" if before == after else "changed"
                rows.append(
                    {
                        "status": status,
                        "type": new_blocks[block_id]["type"],
                        "html": word_diff(before, after) if status == "changed" else escape(after),
                    }
                )
            continue
        for block_id in old_ids[i1:i2]:
            if block_id not in new_blocks:
                block = old_blocks[block_id]
                rows.append({"status": "removed", "type": block["type"], "html": escape(block_text(block))})
        for block_id in new_ids[j1:j2]:
            block = new_blocks[block_id]
            if block_id in old_blocks:
                status = "moved"
                html = word_diff(block_text(old_blocks[block_id]), block_text(block))
            else:
                status, html = "added", escape(block_text(block))
            rows.append({"status": status, "type": block["type"], "html": html})

    for row in rows:
        row["html"] = mark_safe(str(row["html"]).replace("\n", "<br>"))

    old_sources = ", ".join(f"S{n}" for n in old.source_numbers)
    new_sources = ", ".join(f"S{n}" for n in new.source_numbers)
    headline = _text_row("Headline", old.headline, new.headline)
    dek = _text_row("Standfirst", old.dek, new.dek)
    sources = _text_row("Sources", old_sources, new_sources)
    tags = _text_row("Tags", ", ".join(old.tags), ", ".join(new.tags))
    return {
        "headline": headline,
        "dek": dek,
        "sources": sources,
        "tags": tags,
        "top": [headline, dek],
        "bottom": [sources, tags],
        "blocks": rows,
        "changed_blocks": sum(1 for r in rows if r["status"] != "same"),
    }

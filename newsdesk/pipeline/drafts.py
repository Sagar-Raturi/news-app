"""The working draft: what the agents pass between steps, and how it becomes a version.

A working draft is a plain dict with the same fields as an ArticleVersion
(headline, dek, body as raw StreamField data with ids, source_numbers, tags,
seo), so it can be stored in a step's output and resumed after a failure.
"""

import re

from newsdesk.content import block_text, ensure_ids, visible_signature
from newsdesk.publishing import raw_blocks

CITATION = re.compile(r"\s?\[S(\d+)\]")


def from_version(version):
    if version is None:
        return None
    return {
        "headline": version.headline,
        "dek": version.dek,
        "body": [dict(b) for b in version.body],
        "source_numbers": list(version.source_numbers),
        "tags": list(version.tags),
        "seo": dict(version.seo),
    }


def strip_unknown_citations(value, known):
    """Remove [S#] markers that point at no source (they would be invented citations).

    Kept markers are normalised to one space before them, so they survive the
    round trip to the page's numbered links and back unchanged.
    """
    if isinstance(value, str):
        return CITATION.sub(lambda m: f" [S{m.group(1)}]" if int(m.group(1)) in known else "", value)
    if isinstance(value, dict):
        return {k: strip_unknown_citations(v, known) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_unknown_citations(v, known) for v in value]
    return value


def cited_numbers(body, known):
    """Source numbers cited in the body, in order of first citation."""
    seen = []
    for block in body:
        for match in CITATION.finditer(block_text(block)):
            number = int(match.group(1))
            if number in known and number not in seen:
                seen.append(number)
    return seen


def finish(draft, known):
    """Clean citations and recompute which sources the draft cites."""
    draft["body"] = ensure_ids([strip_unknown_citations(b, known) for b in draft["body"]])
    draft["headline"] = CITATION.sub("", draft["headline"]).strip()
    draft["dek"] = strip_unknown_citations(draft["dek"], known)
    draft["source_numbers"] = cited_numbers(draft["body"], known)
    return draft


def from_full_draft(full, known, previous=None):
    """A FullDraft from the writer -> working draft (new block ids throughout)."""
    body = raw_blocks(full.body)
    if not body:
        raise ValueError("The draft had no usable body text.")
    draft = {
        "headline": full.headline,
        "dek": full.standfirst,
        "body": body,
        "source_numbers": [],
        "tags": [t.strip()[:100] for t in full.tags if t.strip()][:4],
        "seo": dict(previous["seo"]) if previous else {},
    }
    return finish(draft, known)


def signature(draft):
    return visible_signature(draft["headline"], draft["dek"], draft["body"], draft["tags"], draft["source_numbers"])


def same_content(draft, version):
    return version is not None and signature(draft) == signature(from_version(version))

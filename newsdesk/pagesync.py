"""Keep the public ArticlePage in step with the workspace's versions.

Each version becomes a Wagtail page revision (never published here); the
page is created with the first version. Source markers [S3] become numbered
links to the source in the page text, and turn back into markers when a hand
edit made in the Wagtail editor is imported as a new version.
"""

import re

from django.utils.html import escape
from django.utils.text import Truncator, slugify

from news.models import ArticleAuthor, ArticlePage

from .content import list_items, normalise_block
from .models import ArticleVersion, Source
from .pipeline.drafts import CITATION, cited_numbers, same_content
from .publishing import unique_slug

MAX_TAGS = 4
PAGE_CITATION = re.compile(r'<a href="([^"]*)">\[(\d+)\]</a>|\[(\d+)\]')


# -- version -> page -------------------------------------------------------------


def _citer(version):
    sources = version.sources()
    position = {s.number: i for i, s in enumerate(sources, start=1)}
    urls = {s.number: s.url for s in sources}

    def rich(html):
        def link(match):
            number = int(match.group(1))
            if number not in position:
                return ""
            label = f"[{position[number]}]"
            if urls[number]:
                return f' <a href="{escape(urls[number])}">{label}</a>'
            return f" {label}"

        return CITATION.sub(link, html or "")

    def plain(text):
        return CITATION.sub(lambda m: f" [{position[int(m.group(1))]}]" if int(m.group(1)) in position else "", text or "")

    def strip(text):
        return CITATION.sub("", text or "")

    return rich, plain, strip


def page_body(version):
    rich, plain, strip = _citer(version)
    body = []
    for block in version.body:
        block = {**block, "value": block.get("value")}
        kind, value = block["type"], block["value"]
        if kind == "paragraph":
            block["value"] = rich(value)
        elif kind == "heading":
            block["value"] = strip(value)
        elif kind == "pullquote":
            block["value"] = {**value, "quote": strip(value.get("quote")), "attribution": strip(value.get("attribution"))}
        elif kind == "key_points":
            block["value"] = {**value, "points": [plain(p) for p in list_items(value.get("points"))]}
        elif kind == "qa":
            block["value"] = {**value, "answer": rich(value.get("answer"))}
        elif kind == "stat":
            block["value"] = {**value, "label": plain(value.get("label"))}
        elif kind == "callout":
            block["value"] = {**value, "body": rich(value.get("body"))}
        body.append(block)
    return body


def page_sources(version):
    return [
        {
            "type": "source",
            "value": {"title": s.title[:255], "publisher": s.publisher[:255], "url": s.url, "note": ""},
        }
        for s in version.sources()
    ]


def ai_note(workspace):
    return Truncator(
        f"Researched and drafted by Manthan Reviews' AI newsroom for the {workspace.desk.section.title} section, "
        "then reviewed and approved by an editor before publication."
    ).chars(300)


def choose_author(workspace):
    if workspace.byline_id:
        return workspace.byline
    profile = getattr(workspace.created_by, "author_profile", None) if workspace.created_by_id else None
    return profile or workspace.desk.default_author


def _apply(page, workspace, version):
    page.title = Truncator(version.headline).chars(255)
    page.standfirst = Truncator(version.dek).chars(300)
    page.article_type = workspace.article_type
    page.body = page_body(version)
    page.sources = page_sources(version)
    page.ai_assisted = True
    page.ai_note = ai_note(workspace)
    if version.seo.get("meta_description"):
        page.search_description = version.seo["meta_description"][:255]
    page.tags.clear()
    tags = [t.strip()[:100] for t in version.tags if t.strip()][:MAX_TAGS]
    if tags:
        page.tags.add(*tags)


def sync_page(workspace, version, user=None):
    """Save the version as a page revision (creating the page the first time). Never publishes."""
    user = user or workspace.created_by
    if workspace.page_id is None:
        section = workspace.desk.section.specific
        slug_source = version.seo.get("slug") or version.headline
        page = ArticlePage(slug=unique_slug(section, slugify(slug_source)[:70] or "draft"), live=False, owner=user)
        _apply(page, workspace, version)
        author = choose_author(workspace)
        if author:
            page.article_authors.add(ArticleAuthor(author=author, sort_order=0))
        section.add_child(instance=page)
        workspace.page = page
        workspace.save(update_fields=["page", "updated_at"])
    else:
        page = ArticlePage.objects.get(pk=workspace.page_id).get_latest_revision_as_object()
        _apply(page, workspace, version)
    revision = page.save_revision(user=user)
    ArticleVersion.objects.filter(pk=version.pk).update(page_revision=revision)
    version.page_revision = revision
    return revision


# -- page -> version (hand edits) -------------------------------------------------


def _uncite(version):
    sources = version.sources()
    by_position = {i: s.number for i, s in enumerate(sources, start=1)}
    by_url = {s.url: s.number for s in version.workspace.sources.exclude(url="")}

    def marker(match):
        url, linked, bare = match.groups()
        position = int(linked or bare)
        number = by_url.get(url) if url else None
        number = number or by_position.get(position)
        return f"[S{number}]" if number else match.group(0)

    def convert(value):
        if isinstance(value, str):
            return PAGE_CITATION.sub(marker, value)
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        if isinstance(value, list):
            return [convert(v) for v in value]
        return value

    return convert


def import_page_edits(workspace, user=None):
    """If someone edited the page in Wagtail since the last version, keep that as a new version."""
    from .versions import create_version

    current = workspace.current_version
    if workspace.page_id is None or current is None:
        return None
    page = ArticlePage.objects.get(pk=workspace.page_id)
    latest = page.get_latest_revision()
    if latest is None or latest.pk == current.page_revision_id:
        return None

    edited = latest.as_object()
    convert = _uncite(current)
    body = [normalise_block({**b, "value": convert(b["value"])}) for b in edited.body.get_prep_value()]
    for source in edited.sources:
        url = (source.value.get("url") or "").strip()
        if url and not workspace.sources.filter(url=url).exists():
            Source.record(workspace, url=url, title=source.value.get("title", ""), origin=Source.Origin.EDITOR)
    known = set(workspace.sources.values_list("number", flat=True))
    draft = {
        "headline": edited.title,
        "dek": edited.standfirst,
        "body": body,
        "source_numbers": cited_numbers(body, known),
        "tags": [tag.name for tag in edited.tags.all()],
    }
    if same_content(draft, current):
        ArticleVersion.objects.filter(pk=current.pk).update(page_revision=latest)
        return None
    editor = latest.user or user
    name = (editor.get_full_name() or editor.get_username()) if editor else "someone"
    return create_version(
        workspace,
        headline=draft["headline"],
        dek=draft["dek"],
        body=draft["body"],
        source_numbers=draft["source_numbers"],
        tags=draft["tags"],
        seo=current.seo,
        origin=ArticleVersion.Origin.HUMAN,
        user=editor,
        change_summary=f"Edited in the page editor by {name}.",
        page_revision=latest,
    )

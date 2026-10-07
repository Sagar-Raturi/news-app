"""Turn an agent's ArticleDraft into an AI-assisted ArticlePage draft in review."""

from django.utils.html import escape
from wagtail.models import WorkflowState
from django.utils.text import Truncator, slugify

from news.models import ArticleAuthor, ArticlePage

from .models import ArticleNote

MAX_TAGS = 4


def paragraphs_html(text):
    """Plain text (blank-line separated) -> escaped <p> HTML. The model never supplies HTML."""
    parts = [" ".join(chunk.split()) for chunk in text.replace("\r\n", "\n").split("\n\n")]
    return "".join(f"<p>{escape(part)}</p>" for part in parts if part)


def body_blocks(draft):
    return raw_blocks(draft.body)


def raw_blocks(draft_blocks):
    """Agent blocks (DraftBlock) -> raw StreamField data. Text is escaped; the model never supplies HTML."""
    blocks = []
    for block in draft_blocks:
        text, detail = block.text.strip(), block.detail.strip()
        if block.type == "paragraph" and text:
            blocks.append({"type": "paragraph", "value": paragraphs_html(text)})
        elif block.type == "heading" and text:
            blocks.append({"type": "heading", "value": text[:255]})
        elif block.type == "pullquote" and text:
            blocks.append({"type": "pullquote", "value": {"quote": text, "attribution": detail[:255]}})
        elif block.type == "key_points" and block.points:
            points = [p.strip()[:255] for p in block.points if p.strip()]
            blocks.append({"type": "key_points", "value": {"title": (text or "Key points")[:255], "points": points}})
        elif block.type == "qa" and text and detail:
            blocks.append({"type": "qa", "value": {"question": text[:255], "answer": paragraphs_html(detail)}})
        elif block.type == "stat" and text and detail:
            blocks.append(
                {"type": "stat", "value": {"figure": text[:255], "label": detail[:255], "source": block.source.strip()[:255]}}
            )
        elif block.type == "callout" and text and detail:
            blocks.append({"type": "callout", "value": {"title": text[:255], "body": paragraphs_html(detail)}})
    return blocks


def safe_sources(draft, source_material):
    """Keep a URL only if it was in the material the editor supplied (no invented links)."""
    sources = []
    for source in draft.sources:
        url = source.url.strip()
        if not url.startswith(("http://", "https://")) or url not in source_material:
            url = ""
        if source.title.strip():
            sources.append(
                {
                    "type": "source",
                    "value": {
                        "title": source.title.strip()[:255],
                        "publisher": source.publisher.strip()[:255],
                        "url": url,
                        "note": "",
                    },
                }
            )
    return sources


def unique_slug(section, headline):
    base = slugify(headline)[:70] or "draft"
    slug, n = base, 2
    while section.get_children().filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def choose_author(request):
    if request.byline_id:
        return request.byline
    profile = getattr(request.requested_by, "author_profile", None) if request.requested_by else None
    return profile or request.desk.default_author


def ai_note(request, model):
    return Truncator(
        f"Drafted by The Ledger's {request.desk.name} AI agent ({model}) from reporting material "
        "supplied by our journalists, then reviewed and edited by an editor before publication."
    ).chars(300)


def create_article(request, result):
    """Create the draft page as the commissioning user and submit it to Editor review."""
    draft = result.draft
    body = body_blocks(draft)
    if not body:
        raise ValueError("The draft had no usable body text.")

    section = request.desk.section.specific
    user = request.requested_by
    article = ArticlePage(
        title=Truncator(draft.headline.strip()).chars(255),
        slug=unique_slug(section, draft.headline),
        standfirst=Truncator(draft.standfirst.strip()).chars(300),
        article_type=request.article_type,
        body=body,
        sources=safe_sources(draft, request.source_material),
        ai_assisted=True,
        ai_note=ai_note(request, result.model),
        live=False,
        owner=user,
    )
    author = choose_author(request)
    if author:
        article.article_authors.add(ArticleAuthor(author=author, sort_order=0))
    tags = [t.strip()[:100] for t in draft.tags if t.strip()][:MAX_TAGS]
    if tags:
        article.tags.add(*tags)

    section.add_child(instance=article)
    article.save_revision(user=user)
    ArticleNote.remember(article, request.article_instructions, ArticleNote.Source.COMMISSION, user)
    workflow = article.get_workflow()
    if workflow:
        workflow.start(article, user)
    return article


def resubmit_for_review(page, user):
    """Send the page (with its latest revision) back into Editor review."""
    page = page.specific_class.objects.get(pk=page.pk)
    state = page.current_workflow_state
    workflow = page.get_workflow()
    if state and state.status == WorkflowState.STATUS_NEEDS_CHANGES:
        # Same as a writer pressing "Resubmit": the review task restarts on the latest revision.
        state.resume(user)
    elif state and state.status == WorkflowState.STATUS_IN_PROGRESS:
        # Review was still open: restart it so the editor reviews the revised text.
        state.cancel(user=user)
        if workflow:
            workflow.start(page, user)
    elif workflow:
        workflow.start(page, user)


def apply_revision(request, result):
    """Rewrite the existing draft as a new page revision; slug, byline and image are kept."""
    page = ArticlePage.objects.get(pk=request.article_id)  # fresh: live state and latest revision
    if page.live:
        raise ValueError("This article is already published; revise it by hand.")
    draft = result.draft
    body = body_blocks(draft)
    if not body:
        raise ValueError("The revision had no usable body text.")

    revised = page.get_latest_revision_as_object()
    revised.title = Truncator(draft.headline.strip()).chars(255)
    revised.standfirst = Truncator(draft.standfirst.strip()).chars(300)
    revised.body = body
    revised.sources = safe_sources(draft, request.source_material + "\n" + request.instructions)
    revised.ai_assisted = True
    revised.ai_note = ai_note(request, result.model)
    tags = [t.strip()[:100] for t in draft.tags if t.strip()][:MAX_TAGS]
    revised.tags.clear()
    if tags:
        revised.tags.add(*tags)
    revised.save_revision(user=request.requested_by)

    resubmit_for_review(page, request.requested_by)
    return page

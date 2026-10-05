from django.db.models import Count, Q
from django.db.models import prefetch_related_objects
from django.shortcuts import get_object_or_404, render
from taggit.models import Tag

from .models import ArticlePage, Author, SectionPage, attach_sections, is_htmx, live_articles, paginate

LIST_PARTIAL = "news/includes/article_list_page.html"


def _render_listing(request, template, context):
    """Full page normally; just the next batch of stories for HTMX "load more"."""
    page_obj = context["page_obj"]
    context["articles"] = attach_sections(page_obj.object_list)
    if is_htmx(request) and request.GET.get("page"):
        return render(request, LIST_PARTIAL, context)
    return render(request, template, context)


def author_list(request):
    authors = Author.objects.annotate(
        article_count=Count("article_authors", filter=Q(article_authors__page__live=True))
    ).order_by("name")
    return render(request, "news/author_list.html", {"authors": authors})


def author_detail(request, slug):
    author = get_object_or_404(Author, slug=slug)
    page_obj = paginate(request, author.live_articles())
    return _render_listing(request, "news/author_detail.html", {"author": author, "page_obj": page_obj})


def tag_detail(request, slug):
    tag = get_object_or_404(Tag, slug=slug)
    articles = live_articles().filter(tags=tag).distinct()
    page_obj = paginate(request, articles)
    return _render_listing(request, "news/tag_detail.html", {"tag": tag, "page_obj": page_obj})


def search(request):
    query = request.GET.get("q", "").strip()
    section_slug = request.GET.get("section", "")
    article_type = request.GET.get("type", "")
    sections = SectionPage.objects.live().in_menu()

    page_obj = None
    articles = []
    authors = []
    if query:
        qs = ArticlePage.objects.live().public()
        section = sections.filter(slug=section_slug).first() if section_slug else None
        if section:
            qs = qs.descendant_of(section)
        if article_type in ArticlePage.ArticleType.values:
            qs = qs.filter(article_type=article_type)
        page_obj = paginate(request, qs.search(query))
        articles = attach_sections(page_obj.object_list)
        prefetch_related_objects(articles, "article_authors__author")
        authors = Author.objects.filter(name__icontains=query)[:4] if len(query) > 2 else []

    context = {
        "query": query,
        "page_obj": page_obj,
        "articles": articles,
        "authors": authors,
        "sections": sections,
        "section_slug": section_slug,
        "article_type": article_type,
        "article_types": ArticlePage.ArticleType.choices,
    }
    if is_htmx(request):
        return render(request, "search/results.html", context)
    return render(request, "search/search.html", context)

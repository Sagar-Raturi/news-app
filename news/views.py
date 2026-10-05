from django.contrib.syndication.views import Feed
from django.db.models import Count, Q, prefetch_related_objects
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import cache_control
from taggit.models import Tag

from core.models import SiteSettings

from .models import ArticlePage, Author, SectionPage, attach_sections, is_htmx, live_articles, paginate
from .seo import author_json_ld, to_json_ld
from .sitemaps import google_news_articles

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
    context = {"author": author, "page_obj": page_obj, "author_json_ld": to_json_ld(author_json_ld(author))}
    return _render_listing(request, "news/author_detail.html", context)


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


@cache_control(max_age=300)
def news_sitemap(request):
    """Google News sitemap: articles published in the last 48 hours."""
    site_settings = SiteSettings.for_request(request)
    context = {
        "articles": google_news_articles(),
        "publication_name": site_settings.site_name,
        "language": site_settings.publication_language,
    }
    return render(request, "news/news_sitemap.xml", context, content_type="application/xml")


def robots_txt(request):
    from core.templatetags.ledger import absolute

    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /django-admin/",
        "Disallow: /search/",
        "",
        f"Sitemap: {absolute(reverse('sitemap'))}",
        f"Sitemap: {absolute(reverse('news:news_sitemap'))}",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


class LatestArticlesFeed(Feed):
    description = "The latest news, analysis and opinion."

    def __call__(self, request, *args, **kwargs):
        self.site_name = SiteSettings.for_request(request).site_name
        return super().__call__(request, *args, **kwargs)

    def title(self):
        return self.site_name

    def link(self):
        return "/"

    def items(self):
        return live_articles()[:30]

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.standfirst

    def item_link(self, item):
        return item.url

    def item_pubdate(self, item):
        return item.display_date

    def item_author_name(self, item):
        return ", ".join(a.name for a in item.authors)

    def item_categories(self, item):
        return [item.get_article_type_display(), *item.tags.names()]

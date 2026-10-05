from datetime import timedelta

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone
from taggit.models import Tag

from .models import ArticlePage, Author, live_articles

# Google News only wants articles from the last two days.
NEWS_SITEMAP_WINDOW = timedelta(hours=getattr(settings, "NEWS_SITEMAP_WINDOW_HOURS", 48))
NEWS_SITEMAP_LIMIT = 1000


class AuthorSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.4

    def items(self):
        return (
            Author.objects.filter(article_authors__page__in=ArticlePage.objects.live().public().values("pk"))
            .annotate(last_article=Max("article_authors__page__last_published_at"))
            .order_by("name")
        )

    def lastmod(self, author):
        return author.last_article


class TagSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.3

    def items(self):
        public_ids = ArticlePage.objects.live().public().values("pk")
        return Tag.objects.filter(news_articlepagetag_items__content_object__in=public_ids).distinct().order_by("name")

    def location(self, tag):
        return reverse("news:tag_detail", args=[tag.slug])


def google_news_articles(now=None):
    since = (now or timezone.now()) - NEWS_SITEMAP_WINDOW
    return live_articles().filter(published_date__gte=since)[:NEWS_SITEMAP_LIMIT]

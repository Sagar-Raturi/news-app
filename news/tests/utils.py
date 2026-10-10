"""Small helpers to build a page tree in tests without the full bootstrap."""

import datetime

from django.utils import timezone
from wagtail.models import Page, Site

from news.models import ArticleAuthor, ArticlePage, Author, HomePage, SectionPage


def make_home():
    root = Page.get_first_root_node()
    home = root.add_child(instance=HomePage(title="Manthan Reviews", slug="ledger-home"))
    Site.objects.update_or_create(
        is_default_site=True,
        defaults={"hostname": "localhost", "port": 80, "root_page": home, "site_name": "Manthan Reviews"},
    )
    return home


def make_section(home, title="Economy", slug=None, **kwargs):
    return home.add_child(instance=SectionPage(title=title, slug=slug or title.lower(), **kwargs))


def make_author(name="Asha Menon", slug=None, **kwargs):
    return Author.objects.create(name=name, slug=slug or name.lower().replace(" ", "-"), **kwargs)


def make_article(section, title="Test article", authors=(), tags=(), days_ago=None, live=True, **kwargs):
    kwargs.setdefault("standfirst", "A short standfirst.")
    kwargs.setdefault("body", [{"type": "paragraph", "value": "<p>Some body text here.</p>"}])
    if days_ago is not None:
        kwargs["published_date"] = timezone.now() - datetime.timedelta(days=days_ago)
    article = ArticlePage(title=title, live=False, **kwargs)
    for order, author in enumerate(authors):
        article.article_authors.add(ArticleAuthor(author=author, sort_order=order))
    if tags:
        article.tags.add(*tags)
    section.add_child(instance=article)
    if live:
        article.save_revision().publish()
    else:
        article.save_revision()
    article.refresh_from_db()
    return article

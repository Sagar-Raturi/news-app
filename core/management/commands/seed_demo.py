import io
import json
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.images import ImageFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from wagtail.images.models import Image
from wagtail.models import Collection, Site

from core.demo_images import illustration
from core.models import SiteSettings
from core.newsroom import bootstrap
from news.models import ArticleAuthor, ArticlePage, Author, HomeFeaturedArticle, SectionPage

CONTENT_FILE = Path(__file__).resolve().parents[2] / "seed_data" / "demo_content.json"
DEMO_COLLECTION = "Demo images"

# Local-development logins (documented in the README). Never use in production.
DEMO_USERS = [
    # username, password, group, linked author slug, superuser
    ("admin", "admin", None, None, True),
    ("editor", "editor", "Editors", "ananya-iyer", False),
    ("writer", "writer", "Writers", "meera-deshpande", False),
]

REVIEW_DRAFT = {
    "slug": "monsoon-session-halfway-report-card",
    "headline": "Monsoon session at the halfway mark: what has passed, what has stalled",
    "standfirst": "Two weeks in, the government has its key bills through one House. The harder votes are still to come.",
    "section": "politics",
    "body": [
        {"type": "paragraph", "value": "<p>Halfway through the monsoon session, the government has moved four of its priority bills through the Lok Sabha, but only one has cleared the Rajya Sabha. Floor managers say the second half will be busier; opposition leaders say it will be noisier.</p>"},
        {"type": "paragraph", "value": "<p>This draft is waiting for an editor. Sign in as <b>editor</b> to approve it or request changes.</p>"},
    ],
}


class Command(BaseCommand):
    help = "Load demo authors, articles, images, About & AI policy content and demo users."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing demo content first")
        parser.add_argument("--if-empty", action="store_true", help="Do nothing if any article exists")

    def handle(self, *args, **options):
        if options["if_empty"] and ArticlePage.objects.exists():
            self.stdout.write("Articles already exist; skipping demo seed.")
            return
        content = json.loads(CONTENT_FILE.read_text(encoding="utf-8"))
        with transaction.atomic():
            if options["reset"]:
                self.reset(content)
            site = bootstrap()
            authors = self.create_authors(content["authors"])
            users = self.create_users(site, authors)
            sections = {s.slug: s for s in SectionPage.objects.child_of(site["home"])}
            articles = self.create_articles(content["articles"], sections, authors, users)
            self.set_top_stories(site["home"], content["articles"], articles)
            self.fill_about_page(site["about"], content["about_page"])
            self.create_review_draft(sections, authors, users)
            self.configure_settings()
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(authors)} authors and {len(articles)} articles. "
                "Logins: admin/admin, editor/editor, writer/writer."
            )
        )

    # -- steps --------------------------------------------------------------

    def reset(self, content):
        """Remove only what this command created (demo slugs and demo images)."""
        slugs = [a["slug"] for a in content["articles"]] + [REVIEW_DRAFT["slug"]]
        for page in ArticlePage.objects.filter(slug__in=slugs):
            page.delete()
        Author.objects.filter(slug__in=[a["slug"] for a in content["authors"]]).delete()
        Image.objects.filter(collection__name=DEMO_COLLECTION).delete()

    def create_authors(self, data):
        authors = {}
        for item in data:
            author, _ = Author.objects.update_or_create(
                slug=item["slug"],
                defaults={"name": item["name"], "role": item["role"], "bio": item["bio"], "twitter": item.get("twitter", "")},
            )
            authors[author.slug] = author
        return authors

    def create_users(self, site, authors):
        User = get_user_model()
        groups = {"Editors": site["editors"], "Writers": site["writers"]}
        users = {}
        for username, password, group, author_slug, superuser in DEMO_USERS:
            user = User.objects.filter(username=username).first()
            if user is None:
                factory = User.objects.create_superuser if superuser else User.objects.create_user
                user = factory(username, f"{username}@example.com", password)
            if group:
                user.groups.add(groups[group])
            if author_slug and author_slug in authors:
                author = authors[author_slug]
                user.first_name, _, user.last_name = author.name.partition(" ")
                user.save()
                author.user = user
                author.save()
            users[username] = user
        return users

    def demo_image(self, slug, section_slug, title, alt):
        collection = Collection.objects.filter(name=DEMO_COLLECTION).first()
        if collection is None:
            collection = Collection.get_first_root_node().add_child(name=DEMO_COLLECTION)
        data = io.BytesIO(illustration(slug, section_slug))
        image = Image(
            title=title[:255], description=alt[:255], collection=collection, file=ImageFile(data, name=f"{slug}.jpg")
        )
        image.save()
        return image

    def create_articles(self, data, sections, authors, users):
        now = timezone.now()
        created = {}
        for item in data:
            section = sections[item["section"]]
            if ArticlePage.objects.filter(slug=item["slug"]).exists():
                created[item["slug"]] = ArticlePage.objects.get(slug=item["slug"])
                continue
            article = ArticlePage(
                title=item["headline"],
                slug=item["slug"],
                standfirst=item["standfirst"],
                article_type=item["type"],
                hero_image=self.demo_image(item["slug"], item["section"], item["headline"], item.get("hero_alt", "")),
                hero_caption=item.get("hero_caption", ""),
                hero_credit="Illustration: The Ledger",
                body=item["body"],
                sources=[{"type": "source", "value": source} for source in item.get("sources", [])],
                ai_assisted=item.get("ai_assisted", False),
                ai_note=item.get("ai_note", ""),
                live=False,
                owner=users["writer"],
            )
            for order, slug in enumerate(item["authors"]):
                article.article_authors.add(ArticleAuthor(author=authors[slug], sort_order=order))
            article.tags.add(*item.get("tags", []))
            section.add_child(instance=article)
            article.save_revision(user=users["writer"]).publish(user=users["editor"])

            published = now - timedelta(days=item["days_ago"])
            ArticlePage.objects.filter(pk=article.pk).update(
                published_date=published, first_published_at=published, last_published_at=published
            )
            created[item["slug"]] = article
        return created

    def set_top_stories(self, home, data, articles):
        HomeFeaturedArticle.objects.filter(page=home).delete()
        featured = sorted((a for a in data if a.get("featured")), key=lambda a: a["days_ago"])
        for order, item in enumerate(featured):
            HomeFeaturedArticle.objects.create(page=home, article=articles[item["slug"]], sort_order=order)
        home.save_revision().publish()

    def fill_about_page(self, about, data):
        about.title = data["title"]
        about.intro = data["intro"]
        about.body = data["body"]
        about.search_description = "Who we are, our editorial standards and how we use AI."
        about.save_revision().publish()

    def create_review_draft(self, sections, authors, users):
        """Leave one article waiting in the Editor review queue."""
        if ArticlePage.objects.filter(slug=REVIEW_DRAFT["slug"]).exists():
            return
        writer = users["writer"]
        article = ArticlePage(
            title=REVIEW_DRAFT["headline"],
            slug=REVIEW_DRAFT["slug"],
            standfirst=REVIEW_DRAFT["standfirst"],
            article_type="news",
            body=REVIEW_DRAFT["body"],
            live=False,
            owner=writer,
        )
        author = getattr(writer, "author_profile", None)
        if author:
            article.article_authors.add(ArticleAuthor(author=author, sort_order=0))
        article.tags.add("Monsoon Session", "Parliament")
        sections[REVIEW_DRAFT["section"]].add_child(instance=article)
        article.save_revision(user=writer)
        workflow = article.get_workflow()
        if workflow:
            workflow.start(article, writer)

    def configure_settings(self):
        site = Site.objects.get(is_default_site=True)
        settings = SiteSettings.for_site(site)
        settings.demo_notice = True
        settings.save()

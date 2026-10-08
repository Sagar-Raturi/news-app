import json
import shutil
import tempfile
from collections import Counter
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from wagtail.models import WorkflowState

from core.management.commands.seed_demo import CONTENT_FILE
from core.models import SiteSettings, StandardPage
from news.models import ArticlePage, Author, HomeFeaturedArticle, HomePage

MEDIA_ROOT = tempfile.mkdtemp(prefix="ledger-test-media-")


class DemoContentFileTests(TestCase):
    """The JSON content file is valid and covers every section and type."""

    def setUp(self):
        self.content = json.loads(CONTENT_FILE.read_text(encoding="utf-8"))

    def test_shape(self):
        articles = self.content["articles"]
        self.assertGreaterEqual(len(articles), 20)
        sections = Counter(a["section"] for a in articles)
        for slug in ["politics", "international", "local", "economy", "society", "education", "health", "science-tech", "opinion"]:
            self.assertGreaterEqual(sections[slug], 2, slug)
        self.assertEqual(set(a["type"] for a in articles), {"news", "analysis", "explainer", "opinion", "editorial"})
        author_slugs = {a["slug"] for a in self.content["authors"]}
        for article in articles:
            self.assertTrue(set(article["authors"]) <= author_slugs, article["slug"])
            self.assertEqual(article["body"][0]["type"], "paragraph", article["slug"])
        self.assertEqual(len({a["slug"] for a in articles}), len(articles))

    def test_about_page_has_ai_policy(self):
        headings = [b["value"] for b in self.content["about_page"]["body"] if b["type"] == "heading"]
        self.assertIn("How we use AI", headings)


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class SeedDemoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with cls.captureOnCommitCallbacks(execute=True):
            call_command("seed_demo", stdout=StringIO())

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def test_articles_authors_and_images(self):
        content = json.loads(CONTENT_FILE.read_text(encoding="utf-8"))
        self.assertEqual(ArticlePage.objects.live().count(), len(content["articles"]))
        self.assertEqual(Author.objects.count(), len(content["authors"]))
        self.assertFalse(ArticlePage.objects.live().filter(hero_image__isnull=True).exists())
        self.assertEqual(ArticlePage.objects.live().filter(ai_assisted=True).count(), 4)

    def test_top_stories_curated(self):
        self.assertEqual(HomeFeaturedArticle.objects.count(), 5)

    def test_about_page_filled(self):
        about = StandardPage.objects.get(slug="about")
        self.assertTrue(about.intro)
        self.assertContains(self.client.get("/about/"), 'href="/ai-policy/"')

    def test_trust_pages_published_with_demo_publisher(self):
        response = self.client.get("/contact/")
        self.assertContains(response, "not a real company")
        for slug in ["ai-policy", "corrections", "contact", "grievances", "terms", "privacy"]:
            self.assertContains(self.client.get("/"), f'href="/{slug}/"')

    def test_demo_users_and_roles(self):
        User = get_user_model()
        self.assertTrue(User.objects.get(username="admin").is_superuser)
        self.assertTrue(User.objects.get(username="editor").groups.filter(name="Editors").exists())
        writer = User.objects.get(username="writer")
        self.assertTrue(writer.groups.filter(name="Writers").exists())
        self.assertEqual(writer.author_profile.slug, "meera-deshpande")

    def test_one_draft_waiting_for_review(self):
        draft = ArticlePage.objects.get(live=False)
        self.assertEqual(
            WorkflowState.objects.get(status=WorkflowState.STATUS_IN_PROGRESS).content_object.specific, draft
        )

    def test_demo_notice_enabled(self):
        home = HomePage.objects.get()
        self.assertTrue(SiteSettings.for_site(home.get_site()).demo_notice)

    def test_if_empty_is_noop(self):
        out = StringIO()
        call_command("seed_demo", "--if-empty", stdout=out)
        self.assertIn("skipping", out.getvalue())

    def test_every_public_page_renders(self):
        urls = ["/", "/search/?q=monsoon", "/authors/", "/sitemap.xml", "/news-sitemap.xml", "/feed/", "/robots.txt"]
        urls += [page.url for page in ArticlePage.objects.live()]
        urls += [a.get_absolute_url() for a in Author.objects.all()]
        urls += [f"/{slug}/" for slug in ["politics", "international", "local", "economy", "society", "education", "health", "science-tech", "opinion", "about", "ai-policy", "corrections", "contact", "grievances", "terms", "privacy"]]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_search_finds_seeded_content(self):
        response = self.client.get("/search/?q=monsoon")
        self.assertGreater(response.context["page_obj"].paginator.count, 0)

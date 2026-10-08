import json
import re
import xml.etree.ElementTree as ET

from django.test import TestCase, override_settings
from wagtail.images.models import Image
from wagtail.images.tests.utils import get_test_image_file

from core.models import StandardPage
from core.newsroom import bootstrap
from news.models import ARTICLES_PER_PAGE, HomeFeaturedArticle, SectionPage

from .utils import make_article, make_author

JSON_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "news": "http://www.google.com/schemas/sitemap-news/0.9"}


def json_ld_blocks(response):
    return [json.loads(block) for block in JSON_LD_RE.findall(response.content.decode())]


@override_settings(SITE_BASE_URL="http://localhost:8000")
class SiteTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Wagtail updates the search index on commit; run those callbacks now.
        with cls.captureOnCommitCallbacks(execute=True):
            cls.build_site()

    @classmethod
    def build_site(cls):
        result = bootstrap()
        cls.home = result["home"]
        cls.about = result["about"]
        cls.sections = {s.slug: s for s in SectionPage.objects.all()}
        cls.image = Image.objects.create(title="Monsoon", file=get_test_image_file(size=(1600, 900)))
        cls.asha = make_author("Asha Menon", role="Economics Correspondent", bio="Covers the economy.")
        cls.ravi = make_author("Ravi Kulkarni", role="Columnist")
        cls.board = make_author("The Editorial Board", slug="editorial-board")

        cls.rbi = make_article(
            cls.sections["economy"],
            title="RBI holds rates as food prices cool",
            standfirst="The central bank keeps its options open.",
            article_type="analysis",
            authors=[cls.asha],
            tags=["RBI", "Inflation"],
            hero_image=cls.image,
            hero_caption="The Reserve Bank's headquarters in Mumbai",
            ai_assisted=True,
            ai_note="AI summarised the policy statement; figures checked by our desk.",
            days_ago=0.2,
            body=[
                {"type": "paragraph", "value": "<p>Monetary policy stayed on hold this week.</p>"},
                {"type": "heading", "value": "What comes next"},
                {"type": "pullquote", "value": {"quote": "Patience is a policy too.", "attribution": "A senior economist"}},
            ],
            sources=[{"type": "source", "value": {"title": "Monetary Policy Statement", "publisher": "RBI", "url": "https://www.rbi.org.in/", "note": ""}}],
        )
        cls.old_news = make_article(
            cls.sections["politics"], title="Monsoon session opens", authors=[cls.ravi], tags=["Parliament"], days_ago=6
        )
        cls.column = make_article(
            cls.sections["opinion"], title="Why cities need heat plans", article_type="opinion", authors=[cls.ravi], days_ago=1
        )
        cls.editorial = make_article(
            cls.sections["opinion"], title="A budget for the many", article_type="editorial", authors=[cls.board], days_ago=0.5
        )
        cls.draft = make_article(cls.sections["economy"], title="Unpublished scoop", authors=[cls.asha], live=False)
        cls.about.intro = "Who we are."
        cls.about.body = [{"type": "heading", "value": "Our AI policy"}, {"type": "paragraph", "value": "<p>Humans decide.</p>"}]
        cls.about.save_revision().publish()
        cls.ai_policy = result["trust_pages"]["ai-policy"]
        cls.ai_policy.save_revision().publish()


class HomePageViewTests(SiteTestCase):
    def test_renders_top_stories_rails_and_sections(self):
        for i in range(4):
            make_article(self.sections["health"], title=f"Fresh health story {i}", days_ago=0.01 * (i + 1))
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "news/home_page.html")
        self.assertEqual(response.context["lead"].title, "Fresh health story 0")
        self.assertIn(self.rbi, response.context["top_stories"])
        self.assertContains(response, "RBI holds rates as food prices cool")
        self.assertContains(response, 'id="opinion-heading"')
        self.assertIn(self.column, response.context["opinion_articles"])
        section_titles = [b["section"].title for b in response.context["section_blocks"]]
        self.assertNotIn("Opinion", section_titles)
        self.assertNotContains(response, "Unpublished scoop")

    def test_stories_not_repeated(self):
        HomeFeaturedArticle.objects.create(page=self.home, article=self.column, sort_order=0)
        response = self.client.get("/")
        self.assertEqual(response.context["lead"], self.column)
        self.assertNotIn(self.column, response.context["opinion_articles"])
        shown = [response.context["lead"], *response.context["top_stories"], *response.context["opinion_articles"]]
        shown += [a for block in response.context["section_blocks"] for a in block["articles"]]
        self.assertEqual(len(shown), len({a.pk for a in shown}))

    def test_private_curated_story_hidden(self):
        from wagtail.models import PageViewRestriction

        PageViewRestriction.objects.create(page=self.old_news, restriction_type="password", password="x")
        HomeFeaturedArticle.objects.create(page=self.home, article=self.old_news, sort_order=0)
        response = self.client.get("/")
        self.assertNotContains(response, "Monsoon session opens")

    def test_curated_lead(self):
        HomeFeaturedArticle.objects.create(page=self.home, article=self.old_news, sort_order=0)
        response = self.client.get("/")
        self.assertEqual(response.context["lead"], self.old_news)

    def test_navigation_lists_sections(self):
        response = self.client.get("/")
        for title in ["Politics", "International", "Local", "Economy", "Society", "Education", "Health", "Science &amp; Tech", "Opinion"]:
            self.assertContains(response, title)

    def test_website_json_ld(self):
        types = [block["@type"] for block in json_ld_blocks(self.client.get("/"))]
        self.assertIn("WebSite", types)


class SectionPageViewTests(SiteTestCase):
    def test_lists_section_articles_only(self):
        response = self.client.get("/economy/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RBI holds rates")
        self.assertNotContains(response, "Monsoon session opens")
        self.assertNotContains(response, "Unpublished scoop")

    def test_type_filter(self):
        response = self.client.get("/opinion/?type=editorial")
        self.assertContains(response, "A budget for the many")
        self.assertNotContains(response, "Why cities need heat plans")

    def test_invalid_type_filter_ignored(self):
        response = self.client.get("/opinion/?type=bogus")
        self.assertEqual(response.context["article_type"], "")

    def test_htmx_load_more(self):
        section = self.sections["health"]
        for i in range(ARTICLES_PER_PAGE + 2):
            make_article(section, title=f"Health story {i}", days_ago=i)
        first = self.client.get("/health/")
        self.assertContains(first, 'hx-get="?page=2"')
        more = self.client.get("/health/?page=2", HTTP_HX_REQUEST="true")
        self.assertEqual(more.status_code, 200)
        self.assertNotContains(more, "<html")
        self.assertContains(more, "Health story 13")
        self.assertNotContains(more, 'hx-get="?page=3"')


class ArticlePageViewTests(SiteTestCase):
    def test_renders_article(self):
        response = self.client.get(self.rbi.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "news/article_page.html")
        self.assertContains(response, "<h1")
        self.assertContains(response, "The central bank keeps its options open.")
        self.assertContains(response, 'href="/authors/asha-menon/"')
        self.assertContains(response, "dropcap")
        self.assertContains(response, "Patience is a policy too.")
        self.assertContains(response, 'id="what-comes-next"')
        self.assertContains(response, "Monetary Policy Statement")
        self.assertContains(response, 'href="/tags/rbi/"')

    def test_ai_disclosure(self):
        response = self.client.get(self.rbi.url)
        self.assertContains(response, "AI-assisted")
        self.assertContains(response, "AI summarised the policy statement")
        self.assertContains(response, 'href="/ai-policy/">Read our AI policy')
        plain = self.client.get(self.old_news.url)
        self.assertNotContains(plain, 'id="ai-disclosure"')

    def test_open_graph_tags(self):
        response = self.client.get(self.rbi.url)
        self.assertContains(response, '<meta property="og:type" content="article">')
        self.assertContains(response, '<meta property="og:title" content="RBI holds rates as food prices cool">')
        self.assertContains(response, f'<link rel="canonical" href="http://localhost:8000{self.rbi.url}">')
        self.assertRegex(response.content.decode(), r'og:image" content="http://localhost:8000/media/images/[^"]+\.png"')
        self.assertContains(response, 'name="twitter:card" content="summary_large_image"')

    def test_news_article_structured_data(self):
        data = next(b for b in json_ld_blocks(self.client.get(self.rbi.url)) if b["@type"] == "NewsArticle")
        self.assertEqual(data["headline"], "RBI holds rates as food prices cool")
        self.assertEqual(data["articleSection"], "Economy")
        self.assertEqual(data["author"][0], {"@type": "Person", "name": "Asha Menon", "url": "http://localhost:8000/authors/asha-menon/", "jobTitle": "Economics Correspondent"})
        self.assertEqual(data["publisher"]["@type"], "NewsMediaOrganization")
        self.assertEqual(len(data["image"]), 3)
        self.assertTrue(all(url.startswith("http://localhost:8000/media/") for url in data["image"]))
        self.assertIn("datePublished", data)
        self.assertIn("dateModified", data)

    def test_editorial_board_is_organization(self):
        data = next(b for b in json_ld_blocks(self.client.get(self.editorial.url)) if b["@type"] == "NewsArticle")
        self.assertEqual(data["author"][0]["@type"], "Organization")

    def test_draft_is_not_public(self):
        self.assertEqual(self.client.get("/economy/unpublished-scoop/").status_code, 404)

    def test_related_articles(self):
        response = self.client.get(self.rbi.url)
        self.assertNotIn(self.rbi, response.context["related_articles"])


class AuthorAndTagViewTests(SiteTestCase):
    def test_author_list(self):
        response = self.client.get("/authors/")
        self.assertContains(response, "Asha Menon")
        self.assertContains(response, "Ravi Kulkarni")

    def test_author_page(self):
        response = self.client.get("/authors/ravi-kulkarni/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Monsoon session opens")
        self.assertContains(response, "Why cities need heat plans")
        self.assertNotContains(response, "RBI holds rates")
        types = [b["@type"] for b in json_ld_blocks(response)]
        self.assertIn("ProfilePage", types)

    def test_author_page_hides_drafts(self):
        self.assertNotContains(self.client.get("/authors/asha-menon/"), "Unpublished scoop")

    def test_unknown_author_404(self):
        self.assertEqual(self.client.get("/authors/nobody/").status_code, 404)

    def test_tag_page(self):
        response = self.client.get("/tags/inflation/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RBI holds rates")
        self.assertNotContains(response, "Monsoon session opens")

    def test_draft_only_tag_404(self):
        self.draft.tags.add("Embargoed")
        self.draft.save()
        self.assertEqual(self.client.get("/tags/embargoed/").status_code, 404)

    def test_unknown_tag_404(self):
        self.assertEqual(self.client.get("/tags/nope/").status_code, 404)


class SearchViewTests(SiteTestCase):
    def test_empty_search(self):
        response = self.client.get("/search/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'role="search"')

    def test_finds_articles_by_headline_and_body(self):
        self.assertContains(self.client.get("/search/?q=monsoon"), "Monsoon session opens")
        self.assertContains(self.client.get("/search/?q=monetary"), "RBI holds rates")

    def test_excludes_drafts(self):
        self.assertNotContains(self.client.get("/search/?q=scoop"), "Unpublished scoop")

    def test_type_and_section_filters(self):
        response = self.client.get("/search/?q=heat&type=editorial")
        self.assertNotContains(response, "Why cities need heat plans")
        response = self.client.get("/search/?q=monsoon&section=economy")
        self.assertNotContains(response, "Monsoon session opens")

    def test_history_restore_gets_full_page(self):
        response = self.client.get("/search/?q=monsoon", HTTP_HX_REQUEST="true", HTTP_HX_HISTORY_RESTORE_REQUEST="true")
        self.assertContains(response, "<html")
        self.assertIn("HX-Request", response["Vary"])

    def test_pagination_links_encode_params(self):
        with self.captureOnCommitCallbacks(execute=True):
            for i in range(ARTICLES_PER_PAGE + 1):
                make_article(self.sections["health"], title=f"Monsoon health note {i}")
        response = self.client.get("/search/", {"q": "monsoon", "type": "a&b"})
        self.assertContains(response, "type=a%26b")

    def test_htmx_returns_results_fragment(self):
        response = self.client.get("/search/?q=monsoon", HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(response, "search/results.html")
        self.assertNotContains(response, "<html")
        self.assertContains(response, "Monsoon session opens")

    def test_matches_authors(self):
        self.assertContains(self.client.get("/search/?q=asha"), 'href="/authors/asha-menon/"')


class AboutPageViewTests(SiteTestCase):
    def test_about_and_ai_policy(self):
        response = self.client.get("/about/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "About us</h1>")
        self.assertContains(response, "Last updated")
        self.assertIsInstance(response.context["page"], StandardPage)


class SitemapTests(SiteTestCase):
    def test_sitemap_lists_pages_authors_and_tags(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        locs = [el.text for el in ET.fromstring(response.content).findall("s:url/s:loc", NS)]
        self.assertIn(f"http://localhost:8000{self.rbi.url}", locs)
        self.assertIn("http://localhost:8000/about/", locs)
        self.assertTrue(any(loc.endswith("/authors/asha-menon/") for loc in locs))
        self.assertTrue(any(loc.endswith("/tags/inflation/") for loc in locs))
        self.assertFalse(any("unpublished-scoop" in loc for loc in locs))

    def test_google_news_sitemap(self):
        response = self.client.get("/news-sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml")
        root = ET.fromstring(response.content)
        urls = {u.find("s:loc", NS).text: u for u in root.findall("s:url", NS)}
        recent = urls[f"http://localhost:8000{self.rbi.url}"]
        self.assertEqual(recent.find("news:news/news:publication/news:name", NS).text, "The Ledger")
        self.assertEqual(recent.find("news:news/news:publication/news:language", NS).text, "en")
        self.assertEqual(recent.find("news:news/news:title", NS).text, "RBI holds rates as food prices cool")
        self.assertIsNotNone(recent.find("news:news/news:publication_date", NS).text)
        # Older than 48 hours: excluded.
        self.assertNotIn(f"http://localhost:8000{self.old_news.url}", urls)

    def test_private_articles_tags_not_in_sitemap(self):
        from wagtail.models import PageViewRestriction

        private = make_article(self.sections["society"], title="Members only", tags=["Secret Topic"])
        PageViewRestriction.objects.create(page=private, restriction_type="password", password="x")
        content = self.client.get("/sitemap.xml").content.decode()
        self.assertNotIn("secret-topic", content)
        self.assertNotIn("members-only", content)

    def test_robots_txt(self):
        response = self.client.get("/robots.txt")
        self.assertContains(response, "Disallow: /admin/")
        self.assertContains(response, "Sitemap: http://localhost:8000/news-sitemap.xml")

    def test_rss_feed(self):
        response = self.client.get("/feed/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RBI holds rates as food prices cool")
        self.assertNotContains(response, "Unpublished scoop")

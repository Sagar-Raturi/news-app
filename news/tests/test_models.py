import datetime

from django.core.exceptions import ValidationError
from django.utils import timezone
from wagtail.test.utils import WagtailPageTestCase

from core.models import StandardPage
from news.models import ArticlePage, HomeFeaturedArticle, HomePage, SectionPage, live_articles

from .utils import make_article, make_author, make_home, make_section


class PageHierarchyTests(WagtailPageTestCase):
    def test_home_allows_sections_and_standard_pages(self):
        self.assertAllowedSubpageTypes(HomePage, {SectionPage, StandardPage})

    def test_sections_only_hold_articles(self):
        self.assertAllowedSubpageTypes(SectionPage, {ArticlePage})
        self.assertAllowedParentPageTypes(SectionPage, {HomePage})

    def test_articles_are_leaves_under_sections(self):
        self.assertAllowedSubpageTypes(ArticlePage, {})
        self.assertAllowedParentPageTypes(ArticlePage, {SectionPage})


class ArticlePageTests(WagtailPageTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.home = make_home()
        cls.economy = make_section(cls.home, "Economy")
        cls.politics = make_section(cls.home, "Politics")
        cls.asha = make_author("Asha Menon", role="Economics Correspondent")
        cls.ravi = make_author("Ravi Kulkarni")

    def test_defaults(self):
        article = make_article(self.economy, authors=[self.asha])
        self.assertEqual(article.article_type, ArticlePage.ArticleType.NEWS)
        self.assertFalse(article.ai_assisted)
        self.assertFalse(article.is_opinion)

    def test_section_is_parent(self):
        article = make_article(self.economy, authors=[self.asha])
        self.assertEqual(article.section, self.economy)
        self.assertEqual(article.url_path.split("/")[-3], "economy")

    def test_authors_keep_byline_order(self):
        article = make_article(self.economy, authors=[self.ravi, self.asha])
        self.assertEqual(article.authors, [self.ravi, self.asha])
        self.assertEqual(list(self.asha.live_articles()), [article])

    def test_tags(self):
        article = make_article(self.economy, tags=["RBI", "Inflation"])
        self.assertEqual(sorted(article.tags.names()), ["Inflation", "RBI"])

    def test_published_date_defaults_to_first_publish(self):
        article = make_article(self.economy)
        self.assertIsNotNone(article.published_date)
        self.assertEqual(article.published_date, article.first_published_at)

    def test_published_date_stable_across_republish(self):
        article = make_article(self.economy)
        original = article.published_date
        article.title = "Updated headline"
        article.save_revision().publish()
        article.refresh_from_db()
        self.assertEqual(article.published_date, original)

    def test_explicit_published_date_kept(self):
        when = timezone.now() - datetime.timedelta(days=3)
        article = make_article(self.economy, published_date=when)
        self.assertEqual(article.published_date, when)
        self.assertEqual(article.display_date, when)

    def test_draft_has_no_published_date(self):
        article = make_article(self.economy, live=False)
        self.assertIsNone(article.published_date)
        self.assertNotIn(article, live_articles())

    def test_standfirst_required(self):
        article = ArticlePage(title="No standfirst", body=[])
        with self.assertRaises(ValidationError):
            article.full_clean()

    def test_reading_time(self):
        body = [{"type": "paragraph", "value": "<p>" + "word " * 460 + "</p>"}]
        article = make_article(self.economy, body=body)
        self.assertEqual(article.word_count, 460)
        self.assertEqual(article.reading_time, 2)

    def test_live_articles_newest_first(self):
        old = make_article(self.economy, title="Old", days_ago=5)
        new = make_article(self.politics, title="New", days_ago=1)
        self.assertEqual(list(live_articles()), [new, old])

    def test_related_articles_prefer_shared_tags(self):
        article = make_article(self.economy, title="A", tags=["RBI"])
        tagged = make_article(self.politics, title="B", tags=["RBI"])
        sibling = make_article(self.economy, title="C")
        related = article.get_related_articles()
        self.assertEqual(related[0], tagged)
        self.assertIn(sibling, related)
        self.assertNotIn(article, related)

    def test_copy_gets_its_own_date(self):
        article = make_article(self.economy, title="Original", days_ago=4)
        copy = article.copy(update_attrs={"slug": "original-copy", "title": "Copy"}, keep_live=False)
        self.assertIsNone(copy.published_date)

    def test_opinion_types(self):
        article = make_article(self.economy, article_type="editorial")
        self.assertTrue(article.is_opinion)


class HomePageTests(WagtailPageTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.home = make_home()
        cls.section = make_section(cls.home, "Politics")

    def test_top_stories_curated_first_then_latest(self):
        older = make_article(self.section, title="Older", days_ago=4)
        newest = make_article(self.section, title="Newest", days_ago=0.1)
        HomeFeaturedArticle.objects.create(page=self.home, article=older, sort_order=0)
        stories = self.home.get_top_stories(2)
        self.assertEqual(stories, [older, newest])

    def test_unpublished_curated_story_skipped(self):
        draft = make_article(self.section, title="Draft", live=False)
        live = make_article(self.section, title="Live")
        HomeFeaturedArticle.objects.create(page=self.home, article=draft, sort_order=0)
        self.assertEqual(self.home.get_top_stories(1), [live])

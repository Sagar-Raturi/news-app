import math

from django.conf import settings
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import models
from django.db.models import F
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.html import strip_tags
from modelcluster.contrib.taggit import ClusterTaggableManager
from modelcluster.fields import ParentalKey
from taggit.models import TaggedItemBase
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel, PageChooserPanel
from wagtail.fields import StreamField
from wagtail.models import Orderable, Page
from wagtail.search import index
from wagtail.snippets.models import register_snippet

from .blocks import ArticleBodyBlock, SourcesBlock

ARTICLES_PER_PAGE = 12
WORDS_PER_MINUTE = 230


def is_htmx(request):
    return request is not None and request.headers.get("HX-Request") == "true"


def paginate(request, queryset, per_page=ARTICLES_PER_PAGE):
    paginator = Paginator(queryset, per_page)
    try:
        return paginator.page(request.GET.get("page", 1))
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)


# --- Authors -----------------------------------------------------------------


@register_snippet
class Author(index.Indexed, models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    role = models.CharField(max_length=120, blank=True, help_text="e.g. Political Editor")
    bio = models.TextField(blank=True)
    photo = models.ForeignKey(
        "wagtailimages.Image", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    twitter = models.CharField(max_length=50, blank=True, help_text="Handle without the @")
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="author_profile",
        help_text="Optional: the newsroom login for this author",
    )

    panels = [
        FieldPanel("name"),
        FieldPanel("slug"),
        FieldPanel("role"),
        FieldPanel("bio"),
        FieldPanel("photo"),
        FieldPanel("twitter"),
        FieldPanel("user"),
    ]

    search_fields = [index.SearchField("name"), index.AutocompleteField("name")]

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("news:author_detail", args=[self.slug])

    @property
    def initials(self):
        return "".join(part[0] for part in self.name.split()[:2]).upper()

    def live_articles(self):
        return live_articles().filter(article_authors__author=self).distinct()


# --- Article querysets ---------------------------------------------------------


def live_articles():
    """All public, live articles, newest first, with byline data prefetched."""
    return (
        ArticlePage.objects.live()
        .public()
        .select_related("hero_image")
        .prefetch_related("article_authors__author")
        .order_by(F("published_date").desc(nulls_last=True), "-first_published_at", "-pk")
    )


def attach_sections(articles):
    """Set each article's section from one query instead of one per article."""
    articles = list(articles)
    sections = {s.path: s for s in SectionPage.objects.all()}
    for article in articles:
        article._section = sections.get(article.path[: -Page.steplen])
    return articles


# --- Pages ---------------------------------------------------------------------


class HomePage(Page):
    intro = models.CharField(
        max_length=255, blank=True, help_text="Optional strapline under the masthead"
    )

    content_panels = Page.content_panels + [
        FieldPanel("intro"),
        InlinePanel(
            "featured_articles",
            label="Top stories",
            heading="Top stories",
            help_text="Curated top stories (first is the lead). Empty slots fill with the latest articles.",
            max_num=7,
        ),
    ]

    parent_page_types = ["wagtailcore.Page"]
    subpage_types = ["news.SectionPage", "core.StandardPage"]
    max_count = 1

    TOP_STORY_COUNT = 5

    def get_top_stories(self, count=TOP_STORY_COUNT):
        curated = [
            item.article.specific
            for item in self.featured_articles.select_related("article").all()
            if item.article and item.article.live
        ][:count]
        stories = list(curated)
        if len(stories) < count:
            stories += list(
                live_articles().exclude(pk__in=[s.pk for s in stories])[: count - len(stories)]
            )
        return attach_sections(stories)

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        top_stories = self.get_top_stories()
        used = {a.pk for a in top_stories}

        opinion = attach_sections(
            live_articles().filter(article_type__in=ArticlePage.OPINION_TYPES)[:5]
        )
        used |= {a.pk for a in opinion}

        explainers = attach_sections(
            live_articles().filter(article_type=ArticlePage.ArticleType.EXPLAINER).exclude(pk__in=used)[:4]
        )
        used |= {a.pk for a in explainers}

        section_blocks = []
        for section in SectionPage.objects.child_of(self).live().filter(show_on_homepage=True):
            articles = list(
                live_articles().child_of(section).exclude(pk__in=used)[:4]
            )
            for article in articles:
                article._section = section
            if articles:
                section_blocks.append({"section": section, "articles": articles})

        context.update(
            lead=top_stories[0] if top_stories else None,
            top_stories=top_stories[1:],
            opinion_articles=opinion,
            explainers=explainers,
            section_blocks=section_blocks,
            latest=attach_sections(live_articles()[:8]),
        )
        return context


class HomeFeaturedArticle(Orderable):
    page = ParentalKey(HomePage, on_delete=models.CASCADE, related_name="featured_articles")
    article = models.ForeignKey("news.ArticlePage", on_delete=models.CASCADE, related_name="+")

    panels = [PageChooserPanel("article", "news.ArticlePage")]


class SectionPage(Page):
    intro = models.TextField(blank=True, help_text="One or two sentences describing the section")
    show_on_homepage = models.BooleanField(
        default=True, help_text="Show a block of this section's latest stories on the homepage"
    )

    content_panels = Page.content_panels + [FieldPanel("intro"), FieldPanel("show_on_homepage")]

    parent_page_types = ["news.HomePage"]
    subpage_types = ["news.ArticlePage"]

    search_fields = Page.search_fields + [index.SearchField("intro")]

    def get_articles(self, article_type=None):
        qs = live_articles().child_of(self)
        if article_type:
            qs = qs.filter(article_type=article_type)
        return qs

    def get_template(self, request, *args, **kwargs):
        if is_htmx(request):
            return "news/includes/article_list_page.html"
        return super().get_template(request, *args, **kwargs)

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        article_type = request.GET.get("type", "")
        if article_type not in ArticlePage.ArticleType.values:
            article_type = ""
        page_obj = paginate(request, self.get_articles(article_type))
        articles = list(page_obj.object_list)
        for article in articles:
            article._section = self
        context.update(
            page_obj=page_obj,
            articles=articles,
            article_type=article_type,
            article_types=ArticlePage.ArticleType.choices,
            base_query=f"type={article_type}&" if article_type else "",
        )
        return context


class ArticlePageTag(TaggedItemBase):
    content_object = ParentalKey(
        "news.ArticlePage", on_delete=models.CASCADE, related_name="tagged_items"
    )


class ArticleAuthor(Orderable):
    page = ParentalKey("news.ArticlePage", on_delete=models.CASCADE, related_name="article_authors")
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="article_authors")

    panels = [FieldPanel("author")]

    class Meta(Orderable.Meta):
        unique_together = [("page", "author")]


class ArticlePage(Page):
    class ArticleType(models.TextChoices):
        NEWS = "news", "News"
        ANALYSIS = "analysis", "Analysis"
        EXPLAINER = "explainer", "Explainer"
        OPINION = "opinion", "Opinion"
        EDITORIAL = "editorial", "Editorial"

    OPINION_TYPES = [ArticleType.OPINION, ArticleType.EDITORIAL]

    article_type = models.CharField(
        "type", max_length=20, choices=ArticleType.choices, default=ArticleType.NEWS
    )
    standfirst = models.TextField(
        max_length=300, help_text="The summary line under the headline (max 300 characters)"
    )
    hero_image = models.ForeignKey(
        "wagtailimages.Image", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    hero_caption = models.CharField(max_length=255, blank=True)
    hero_credit = models.CharField(max_length=120, blank=True)
    body = StreamField(ArticleBodyBlock())
    sources = StreamField(
        SourcesBlock(), blank=True, help_text="Sources and references cited in the article"
    )
    published_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Shown as the publication date. Leave blank to use the first publish time.",
    )
    ai_assisted = models.BooleanField(
        "AI-assisted",
        default=False,
        help_text="Tick if AI tools helped produce this article (see the AI policy)",
    )
    ai_note = models.CharField(
        "AI disclosure note",
        max_length=300,
        blank=True,
        help_text="How AI was used, e.g. ‘AI summarised the 300-page report; figures checked by our desk.’",
    )
    tags = ClusterTaggableManager(through=ArticlePageTag, blank=True)

    content_panels = [
        FieldPanel("title", heading="Headline"),
        FieldPanel("standfirst"),
        MultiFieldPanel(
            [FieldPanel("article_type"), InlinePanel("article_authors", label="Author", min_num=1)],
            heading="Type and byline",
        ),
        MultiFieldPanel(
            [FieldPanel("hero_image"), FieldPanel("hero_caption"), FieldPanel("hero_credit")],
            heading="Hero image",
        ),
        FieldPanel("body"),
        FieldPanel("sources"),
        MultiFieldPanel(
            [FieldPanel("tags"), FieldPanel("published_date")], heading="Tags and date"
        ),
        MultiFieldPanel(
            [FieldPanel("ai_assisted"), FieldPanel("ai_note")], heading="AI disclosure"
        ),
    ]

    parent_page_types = ["news.SectionPage"]
    subpage_types = []

    search_fields = Page.search_fields + [
        index.SearchField("standfirst"),
        index.SearchField("body"),
        index.FilterField("article_type"),
        index.FilterField("published_date"),
        index.RelatedFields("tags", [index.SearchField("name")]),
    ]

    class Meta:
        verbose_name = "article"

    def save(self, *args, **kwargs):
        # Keep the public date stable: once published, default to the first
        # publish time (preserved by Wagtail across revisions).
        if self.published_date is None:
            if self.first_published_at:
                self.published_date = self.first_published_at
            elif self.live:
                self.published_date = timezone.now()
        super().save(*args, **kwargs)

    @property
    def headline(self):
        return self.title

    @property
    def section(self):
        if not hasattr(self, "_section"):
            parent = self.get_parent()
            self._section = parent.specific if parent else None
        return self._section

    @property
    def display_date(self):
        return self.published_date or self.first_published_at or self.latest_revision_created_at

    @property
    def authors(self):
        return [item.author for item in self.article_authors.all()]

    @property
    def is_opinion(self):
        return self.article_type in self.OPINION_TYPES

    @cached_property
    def word_count(self):
        words = 0
        for block in self.body:
            if block.block_type in {"paragraph"}:
                words += len(strip_tags(block.value.source).split())
            elif block.block_type == "qa":
                words += len(block.value["question"].split())
                words += len(strip_tags(block.value["answer"].source).split())
            elif block.block_type in {"heading"}:
                words += len(str(block.value).split())
        return words

    @property
    def reading_time(self):
        return max(1, math.ceil(self.word_count / WORDS_PER_MINUTE))

    def get_related_articles(self, count=3):
        tag_ids = list(self.tags.values_list("pk", flat=True))
        qs = live_articles().exclude(pk=self.pk)
        related = []
        if tag_ids:
            related = list(qs.filter(tags__in=tag_ids).distinct()[:count])
        if len(related) < count:
            related += list(
                qs.sibling_of(self, inclusive=False)
                .exclude(pk__in=[a.pk for a in related])[: count - len(related)]
            )
        return attach_sections(related)

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context["related_articles"] = self.get_related_articles()
        return context

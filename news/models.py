import math

from django.conf import settings
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import models
from django.db.models import F, Window
from django.db.models.functions import RowNumber, Substr
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
    """True for HTMX partial requests (not history restores, which need full pages)."""
    return (
        request is not None
        and request.headers.get("HX-Request") == "true"
        and not request.headers.get("HX-History-Restore-Request")
    )


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
        .prefetch_related("article_authors__author", "hero_image__renditions")
        .order_by(F("published_date").desc(nulls_last=True), "-first_published_at", "-pk")
    )


def sections_by_path():
    return {s.path: s for s in SectionPage.objects.all()}


def attach_sections(articles, sections=None):
    """Set each article's section from one query instead of one per article."""
    articles = list(articles)
    sections = sections_by_path() if sections is None else sections
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

    def get_top_stories(self, count=TOP_STORY_COUNT, base=None, sections=None):
        base = live_articles() if base is None else base
        curated_ids = [item.article_id for item in self.featured_articles.all()]
        # Only curated stories that are still live and public, in curated order.
        by_id = {a.pk: a for a in base.filter(pk__in=curated_ids)}
        stories = [by_id[pk] for pk in curated_ids if pk in by_id][:count]
        if len(stories) < count:
            stories += list(base.exclude(pk__in=[s.pk for s in stories])[: count - len(stories)])
        return attach_sections(stories, sections)

    def get_section_blocks(self, base, exclude_ids, per_section=4):
        """Latest stories per homepage section in a single query (window function)."""
        sections = list(SectionPage.objects.child_of(self).live().filter(show_on_homepage=True))
        if not sections:
            return []
        prefix_len = len(self.path) + Page.steplen
        section_path = Substr("path", 1, prefix_len)
        rows = (
            base.descendant_of(self)
            .filter(depth=self.depth + 2)
            .exclude(pk__in=exclude_ids)
            .annotate(
                section_path=section_path,
                row=Window(
                    RowNumber(),
                    partition_by=section_path,
                    order_by=[F("published_date").desc(nulls_last=True), F("first_published_at").desc(), F("pk").desc()],
                ),
            )
            .filter(row__lte=per_section)
        )
        grouped = {}
        for article in rows:
            grouped.setdefault(article.section_path, []).append(article)
        blocks = []
        for section in sections:
            articles = grouped.get(section.path, [])
            for article in articles:
                article._section = section
            if articles:
                blocks.append({"section": section, "articles": articles})
        return blocks

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        # Build the base queryset once: .public() queries view restrictions on creation.
        base = live_articles()
        sections = sections_by_path()
        top_stories = self.get_top_stories(base=base, sections=sections)
        used = {a.pk for a in top_stories}

        opinion = attach_sections(
            base.filter(article_type__in=ArticlePage.OPINION_TYPES).exclude(pk__in=used)[:5], sections
        )
        used |= {a.pk for a in opinion}

        explainers = attach_sections(
            base.filter(article_type=ArticlePage.ArticleType.EXPLAINER).exclude(pk__in=used)[:4], sections
        )
        used |= {a.pk for a in explainers}

        section_blocks = self.get_section_blocks(base, used)

        context.update(
            lead=top_stories[0] if top_stories else None,
            top_stories=top_stories[1:],
            opinion_articles=opinion,
            explainers=explainers,
            section_blocks=section_blocks,
            latest=attach_sections(base[:6], sections),
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
        ordering = ["sort_order", "pk"]
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
    # A copy is a new story: it gets its own date when first published.
    exclude_fields_in_copy = ["published_date"]

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

    @cached_property
    def authors(self):
        items = self.article_authors.all()
        if "article_authors" not in getattr(self, "_prefetched_objects_cache", {}):
            items = items.select_related("author")
        return [item.author for item in items]

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
        # self.tags may be an in-memory FakeQuerySet during previews.
        tag_ids = [tag.pk for tag in self.tags.all()]
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

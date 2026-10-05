from django.db import models
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting
from wagtail.fields import StreamField
from wagtail.models import Page
from wagtail.search import index

from news.blocks import ArticleBodyBlock


class StandardPage(Page):
    """Simple content page, e.g. About & AI policy."""

    intro = models.TextField(blank=True)
    body = StreamField(ArticleBodyBlock(), blank=True)

    content_panels = Page.content_panels + [FieldPanel("intro"), FieldPanel("body")]

    parent_page_types = ["news.HomePage", "core.StandardPage"]
    subpage_types = ["core.StandardPage"]

    search_fields = Page.search_fields + [index.SearchField("intro"), index.SearchField("body")]


@register_setting(icon="site")
class SiteSettings(BaseSiteSetting):
    site_name = models.CharField(max_length=80, default="The Ledger")
    tagline = models.CharField(
        max_length=160, default="News, analysis and argument from India"
    )
    publication_language = models.CharField(
        max_length=10, default="en", help_text="ISO 639 code used in the Google News sitemap"
    )
    twitter_handle = models.CharField(max_length=50, blank=True, help_text="Without the @")
    default_share_image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Used for Open Graph cards when a page has no image of its own",
    )
    demo_notice = models.BooleanField(
        default=False, help_text="Show a ‘demonstration content’ notice in the footer"
    )

    panels = [
        MultiFieldPanel(
            [FieldPanel("site_name"), FieldPanel("tagline"), FieldPanel("publication_language")],
            heading="Publication",
        ),
        MultiFieldPanel(
            [FieldPanel("twitter_handle"), FieldPanel("default_share_image")], heading="Social"
        ),
        FieldPanel("demo_notice"),
    ]

    class Meta:
        verbose_name = "site settings"

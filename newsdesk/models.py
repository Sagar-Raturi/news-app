"""AI desk agents: one writing agent per desk, each with a style guide and memory.

A DeskAgent is configuration, not a running process. When an editor
commissions a draft (DraftRequest), a Celery task builds the agent's prompt
from the house rules, the desk's style guide and its feedback memory, asks
Claude for a structured draft, saves it as an AI-assisted ArticlePage draft and
submits it to Editor review. Agents never publish.
"""

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.html import format_html
from django.utils.text import Truncator
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.forms import WagtailAdminModelForm
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel

from news.models import ArticlePage

# The AI policy says AI never writes opinion or editorials.
AGENT_ARTICLE_TYPES = [
    (value, label)
    for value, label in ArticlePage.ArticleType.choices
    if value not in ArticlePage.OPINION_TYPES
]

MODEL_CHOICES = [
    ("claude-opus-5-5", "Claude Opus 5.5 (best quality)"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5 (faster, cheaper)"),
]

EFFORT_CHOICES = [
    ("medium", "Medium"),
    ("high", "High (recommended)"),
    ("xhigh", "Extra high"),
]

# Most recent notes win if a desk accumulates a very long memory.
MEMORY_LIMIT = 50


class DeskAgent(ClusterableModel):
    name = models.CharField(max_length=80, help_text="e.g. Politics desk")
    slug = models.SlugField(max_length=80, unique=True)
    section = models.ForeignKey(
        "news.SectionPage",
        on_delete=models.PROTECT,
        related_name="desk_agents",
        help_text="Drafts from this desk are filed in this section",
    )
    style_guide = models.TextField(
        help_text="How this desk writes: priorities, tone, structure, what to avoid. "
        "Written as instructions to the writer."
    )
    default_author = models.ForeignKey(
        "news.Author",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Byline used when the person commissioning a draft has no author profile",
    )
    model = models.CharField(max_length=40, choices=MODEL_CHOICES, default="claude-opus-5-5")
    effort = models.CharField(
        max_length=10,
        choices=EFFORT_CHOICES,
        default="high",
        help_text="How hard the model thinks. Higher is slower and costs more.",
    )
    active = models.BooleanField(default=True)

    panels = [
        MultiFieldPanel(
            [FieldPanel("name"), FieldPanel("slug"), FieldPanel("section"), FieldPanel("active")],
            heading="Desk",
        ),
        FieldPanel("style_guide"),
        FieldPanel("default_author"),
        MultiFieldPanel([FieldPanel("model"), FieldPanel("effort")], heading="Model"),
        InlinePanel(
            "feedback",
            heading="Memory: feedback for this desk",
            label="Feedback note",
            help_text="Every note here is given to this desk's agent on every draft. "
            "Pick an article type to apply a note only to that type.",
        ),
    ]

    class Meta:
        ordering = ["name"]
        verbose_name = "desk agent"

    def __str__(self):
        return self.name

    def memory_size(self):
        return self.feedback.filter(active=True).count()

    memory_size.short_description = "Memory notes"

    def memory(self, article_type):
        """Active feedback notes that apply to this article type, oldest first."""
        notes = (
            self.feedback.filter(active=True)
            .filter(models.Q(article_type="") | models.Q(article_type=article_type))
            .order_by("-created_at", "-pk")[:MEMORY_LIMIT]
        )
        return list(reversed(notes))


class DeskFeedback(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "Added by an editor"
        REVIEW = "review", "From a review comment"

    desk = ParentalKey(DeskAgent, on_delete=models.CASCADE, related_name="feedback")
    article_type = models.CharField(
        max_length=20,
        choices=AGENT_ARTICLE_TYPES,
        blank=True,
        help_text="Leave blank to apply to every article type",
    )
    note = models.TextField()
    active = models.BooleanField(default=True, help_text="Untick to make the agent forget this note")
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL, editable=False)
    article = models.ForeignKey(
        "news.ArticlePage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    panels = [FieldPanel("article_type"), FieldPanel("note"), FieldPanel("active")]

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return Truncator(self.note).chars(60)


class CommissionForm(WagtailAdminModelForm):
    """Records who commissioned the draft and offers only active desks."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "desk" in self.fields:
            self.fields["desk"].queryset = DeskAgent.objects.filter(active=True)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.requested_by_id is None and self.for_user is not None:
            instance.requested_by = self.for_user
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class DraftRequest(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        WRITING = "writing", "Writing"
        DONE = "done", "In review"
        FAILED = "failed", "Failed"

    desk = models.ForeignKey(DeskAgent, on_delete=models.PROTECT, related_name="requests")
    article_type = models.CharField(max_length=20, choices=AGENT_ARTICLE_TYPES, default="news")
    brief = models.TextField(
        help_text="What the story is, the angle you want, and anything the writer must cover"
    )
    source_material = models.TextField(
        help_text="Paste the reporting the agent may use: notes, statements, report extracts, "
        "data, links. The agent is told to use only this material."
    )
    byline = models.ForeignKey(
        "news.Author",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Leave blank to use your own author profile, or the desk's default author",
    )

    # Set when this request asks the agent to revise an existing draft.
    revision_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="revisions", editable=False
    )
    instructions = models.TextField(blank=True, editable=False, help_text="What the editor asked the agent to change")

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED, editable=False)
    article = models.ForeignKey(
        "news.ArticlePage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    editor_notes = models.TextField(blank=True, editable=False, help_text="What the agent says needs checking")
    error = models.TextField(blank=True, editable=False)
    model_used = models.CharField(max_length=60, blank=True, editable=False)
    input_tokens = models.PositiveIntegerField(default=0, editable=False)
    output_tokens = models.PositiveIntegerField(default=0, editable=False)
    cache_read_tokens = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    base_form_class = CommissionForm

    panels = [
        FieldPanel("desk", widget=forms.Select),
        FieldPanel("article_type"),
        FieldPanel("brief"),
        FieldPanel("source_material"),
        FieldPanel("byline"),
    ]

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "draft commission"

    def __str__(self):
        kind = "Revision" if self.is_revision else self.get_article_type_display()
        return f"{self.desk} · {kind} · {Truncator(self.instructions or self.brief).chars(50)}"

    @property
    def is_revision(self):
        return self.revision_of_id is not None

    @classmethod
    def original_for(cls, page):
        """The commission that first created this article, if an agent wrote it."""
        return cls.objects.filter(article_id=page.pk, revision_of__isnull=True).select_related("desk").first()

    @classmethod
    def pending_for(cls, page):
        return cls.objects.filter(article_id=page.pk, status__in=[cls.Status.QUEUED, cls.Status.WRITING]).exists()

    def clean(self):
        if self.article_type in ArticlePage.OPINION_TYPES:
            raise ValidationError({"article_type": "AI agents do not write opinion or editorials (see the AI policy)."})
        if self.desk_id and not self.desk.active:
            raise ValidationError({"desk": "This desk is switched off."})

    # -- admin list helpers -------------------------------------------------

    def status_label(self):
        return self.get_status_display()

    status_label.short_description = "Status"

    def type_label(self):
        label = self.get_article_type_display()
        return f"{label} (revision)" if self.is_revision else label

    type_label.short_description = "Type"

    def short_brief(self):
        if self.is_revision:
            return Truncator(f"Revise: {self.instructions}").chars(70)
        return Truncator(self.brief).chars(70)

    short_brief.short_description = "Brief"

    def article_link(self):
        if not self.article_id:
            return Truncator(self.error).chars(80) if self.status == self.Status.FAILED else ""
        url = reverse("wagtailadmin_pages:edit", args=[self.article_id])
        return format_html('<a href="{}">{}</a>', url, self.article.title)

    article_link.short_description = "Draft"

    def get_article_display(self):
        """Used by the admin inspect view."""
        return self.article_link() or "—"

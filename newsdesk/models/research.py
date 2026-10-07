"""What the agents found and checked: sources, research findings, fact-check flags.

All scoped to one workspace. Sources are numbered per article so the draft
can cite them ([S3]) and the citations survive revisions.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import Truncator


class Source(models.Model):
    class Origin(models.TextChoices):
        SEARCH = "search", "Web search"
        FETCH = "fetch", "Web page read by an agent"
        EDITOR = "editor", "Supplied by the editor"

    workspace = models.ForeignKey("newsdesk.ArticleWorkspace", on_delete=models.CASCADE, related_name="sources")
    number = models.PositiveIntegerField()
    url = models.URLField(max_length=2000, blank=True)
    title = models.CharField(max_length=500)
    publisher = models.CharField(max_length=255, blank=True)
    origin = models.CharField(max_length=6, choices=Origin.choices, default=Origin.SEARCH)
    excerpt = models.TextField(blank=True, help_text="What the agents took from it")
    accessed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "number"], name="unique_source_number"),
            models.UniqueConstraint(
                fields=["workspace", "url"], condition=~models.Q(url=""), name="unique_source_url"
            ),
        ]

    def __str__(self):
        return f"[S{self.number}] {Truncator(self.title).chars(70)}"

    @classmethod
    def record(cls, workspace, url="", title="", publisher="", origin=Origin.SEARCH, excerpt=""):
        """Add a source to the workspace (or return the existing one for that URL)."""
        url = (url or "").strip()
        if url:
            existing = cls.objects.filter(workspace=workspace, url=url).first()
            if existing:
                if excerpt and excerpt not in existing.excerpt:
                    existing.excerpt = f"{existing.excerpt}\n{excerpt}".strip()
                    existing.save(update_fields=["excerpt"])
                return existing
        number = (cls.objects.filter(workspace=workspace).aggregate(n=models.Max("number"))["n"] or 0) + 1
        return cls.objects.create(
            workspace=workspace,
            number=number,
            url=url,
            title=(title or url or "Untitled source")[:500],
            publisher=publisher[:255],
            origin=origin,
            excerpt=excerpt,
        )


class Finding(models.Model):
    """One research note: a fact, figure, quote or perspective, tied to its source."""

    class Kind(models.TextChoices):
        FACT = "fact", "Fact"
        FIGURE = "figure", "Figure"
        QUOTE = "quote", "Quote"
        BACKGROUND = "background", "Background"
        PERSPECTIVE = "perspective", "Perspective"

    workspace = models.ForeignKey("newsdesk.ArticleWorkspace", on_delete=models.CASCADE, related_name="findings")
    source = models.ForeignKey(Source, null=True, blank=True, on_delete=models.SET_NULL, related_name="findings")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.FACT)
    text = models.TextField()
    detail = models.TextField(blank=True, help_text="Exact wording, data or context from the source")
    step = models.ForeignKey(
        "newsdesk.AgentStep", null=True, blank=True, on_delete=models.SET_NULL, related_name="findings"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return Truncator(self.text).chars(80)


class FactCheckFlag(models.Model):
    class Severity(models.TextChoices):
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        FIXED = "fixed", "Fixed"
        DISMISSED = "dismissed", "Accepted by editor"

    workspace = models.ForeignKey("newsdesk.ArticleWorkspace", on_delete=models.CASCADE, related_name="flags")
    version = models.ForeignKey("newsdesk.ArticleVersion", on_delete=models.CASCADE, related_name="flags")
    block_id = models.CharField(max_length=64, blank=True)
    claim = models.TextField(help_text="The claim as it appears in the draft")
    severity = models.CharField(max_length=6, choices=Severity.choices)
    issue = models.TextField(help_text="What is wrong or unsupported")
    suggestion = models.TextField(blank=True)
    sources = models.ManyToManyField(Source, blank=True, related_name="flags")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    step = models.ForeignKey("newsdesk.AgentStep", null=True, blank=True, on_delete=models.SET_NULL, related_name="flags")
    created_at = models.DateTimeField(auto_now_add=True)

    SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"[{self.severity}] {Truncator(self.claim).chars(60)}"

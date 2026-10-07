"""The article workspace: one AI-written article, its brief, versions and session.

ArticleWorkspace is the "Article" of the AI pipeline. It exists from the
moment an editor writes a brief; the public ArticlePage is created when the
first draft arrives and receives a new Wagtail revision for every version.
Everything the agents know about the article lives on rows that point at this
workspace, which is what keeps one article's session apart from another's.
"""

from django.conf import settings
from django.db import models
from django.utils.text import Truncator

from newsdesk.content import block_text, word_count

from .desks import AGENT_ARTICLE_TYPES


class ArticleWorkspace(models.Model):
    class Status(models.TextChoices):
        BRIEF = "brief", "Brief"
        WORKING = "working", "Agents working"
        ATTENTION = "attention", "Needs attention"
        READY = "ready", "Ready for review"
        APPROVED = "approved", "Approved"
        PUBLISHED = "published", "Published"

    topic = models.ForeignKey("newsdesk.Topic", on_delete=models.PROTECT, related_name="articles")
    desk = models.ForeignKey(
        "newsdesk.DeskAgent", on_delete=models.PROTECT, related_name="workspaces", verbose_name="section"
    )
    article_type = models.CharField("type", max_length=20, choices=AGENT_ARTICLE_TYPES, default="analysis")

    # The brief
    brief = models.TextField(help_text="What you want: the story, the question to answer, why now")
    target_words = models.PositiveIntegerField(
        "target length (words)", null=True, blank=True, help_text="Leave blank for the type's usual length"
    )
    tone = models.CharField(max_length=200, blank=True, help_text="e.g. measured, explanatory, brisk")
    angle = models.TextField("angle / viewpoint", blank=True, help_text="The argument or lens you want")
    audience = models.CharField(max_length=200, blank=True, help_text="e.g. general reader, policy watchers")
    must_include = models.TextField(blank=True, help_text="Points, data or perspectives that must appear (one per line)")
    sources_to_use = models.TextField(
        blank=True, help_text="Links, documents or pasted material the agents should use (one per line)"
    )
    sources_to_avoid = models.TextField(blank=True, help_text="Outlets, sites or kinds of source to avoid")
    byline = models.ForeignKey(
        "news.Author",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Leave blank to use your own author profile, or the section's default author",
    )

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.BRIEF, editable=False)
    page = models.OneToOneField(
        "news.ArticlePage", null=True, blank=True, on_delete=models.SET_NULL, related_name="workspace", editable=False
    )
    current_version = models.ForeignKey(
        "newsdesk.ArticleVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    approved_version = models.ForeignKey(
        "newsdesk.ArticleVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    approved_at = models.DateTimeField(null=True, blank=True, editable=False)
    published_version = models.ForeignKey(
        "newsdesk.ArticleVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    published_at = models.DateTimeField(null=True, blank=True, editable=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-pk"]
        verbose_name = "AI article"
        permissions = [("approve_articleworkspace", "Can approve and publish AI articles")]

    def __str__(self):
        return Truncator(self.title).chars(80)

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating:
            ArticleSession.objects.get_or_create(workspace=self)

    @property
    def title(self):
        return self.current_version.headline if self.current_version_id else self.topic.title

    @property
    def session(self):
        return ArticleSession.objects.get_or_create(workspace=self)[0]

    def active_run(self):
        from .runs import AgentRun

        return self.runs.filter(status__in=AgentRun.ACTIVE).first()

    def next_version_number(self):
        latest = self.versions.order_by("-number").values_list("number", flat=True).first()
        return (latest or 0) + 1

    def open_high_flags(self):
        if not self.current_version_id:
            return self.flags.none()
        return self.flags.filter(version_id=self.current_version_id, status="open", severity="high")

    def compute_status(self):
        from .runs import AgentRun

        if self.active_run():
            return self.Status.WORKING
        if not self.current_version_id:
            return self.Status.BRIEF
        current = self.current_version_id
        if self.published_version_id == current and self.page_id and self.page.live:
            return self.Status.PUBLISHED
        if self.approved_version_id == current:
            return self.Status.APPROVED
        last_run = self.runs.order_by("-created_at", "-pk").first()
        if (last_run and last_run.status == AgentRun.Status.FAILED) or self.open_high_flags().exists():
            return self.Status.ATTENTION
        return self.Status.READY

    def refresh_status(self):
        status = self.compute_status()
        if status != self.status:
            self.status = status
            self.save(update_fields=["status", "updated_at"])
        return status


class ArticleVersion(models.Model):
    """One complete draft. Versions are only ever added, never changed."""

    class Origin(models.TextChoices):
        AGENT = "agent", "Agents"
        HUMAN = "human", "Editor"

    workspace = models.ForeignKey(ArticleWorkspace, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    headline = models.CharField(max_length=255)
    dek = models.TextField("standfirst", max_length=300)
    body = models.JSONField(default=list, help_text="Raw StreamField data, same shape as ArticlePage.body")
    source_numbers = models.JSONField(default=list, help_text="Numbers of the workspace sources cited, in order")
    tags = models.JSONField(default=list)
    seo = models.JSONField(default=dict, help_text="headline_options, meta_description, slug")
    origin = models.CharField("created by", max_length=6, choices=Origin.choices, default=Origin.AGENT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    run = models.ForeignKey(
        "newsdesk.AgentRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="versions"
    )
    based_on = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    change_summary = models.TextField(blank=True)
    page_revision = models.ForeignKey(
        "wagtailcore.Revision", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [models.UniqueConstraint(fields=["workspace", "number"], name="unique_version_number")]

    def __str__(self):
        return f"v{self.number}: {Truncator(self.headline).chars(60)}"

    def block(self, block_id):
        return next((b for b in self.body if b.get("id") == block_id), None)

    def block_text(self, block_id):
        block = self.block(block_id)
        return block_text(block) if block else ""

    @property
    def word_count(self):
        return word_count(self.body)

    def sources(self):
        """Cited sources in citation order."""
        by_number = {s.number: s for s in self.workspace.sources.filter(number__in=self.source_numbers)}
        return [by_number[n] for n in self.source_numbers if n in by_number]


class ArticleSession(models.Model):
    """One article's AI session: its conversation and a rolling summary of older turns."""

    workspace = models.OneToOneField(ArticleWorkspace, on_delete=models.CASCADE, related_name="ai_session")
    summary = models.TextField(blank=True, help_text="Summary of the turns older than summarised_through")
    summarised_through = models.ForeignKey(
        "newsdesk.SessionMessage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Session for {self.workspace}"


class SessionMessage(models.Model):
    class Role(models.TextChoices):
        EDITOR = "editor", "Editor"
        ORCHESTRATOR = "orchestrator", "Orchestrator"
        AGENT = "agent", "Agent"
        SYSTEM = "system", "System"

    class Status(models.TextChoices):
        NONE = "", "—"
        OPEN = "open", "Waiting for the agents"
        ADDRESSED = "addressed", "Addressed"
        DISMISSED = "dismissed", "Withdrawn"

    session = models.ForeignKey(ArticleSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=12, choices=Role.choices)
    agent_role = models.CharField(max_length=20, blank=True)
    content = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, blank=True, default=Status.NONE)
    pinned = models.BooleanField(
        default=False, help_text="Keep applying this instruction to every later revision of this article"
    )
    version = models.ForeignKey(
        ArticleVersion, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    run = models.ForeignKey(
        "newsdesk.AgentRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.get_role_display()}: {Truncator(self.content).chars(60)}"


class InlineComment(models.Model):
    """A comment on a passage of one version, re-anchored onto later versions.

    The anchor is the block id plus the exact quoted text and a little context
    either side. If a later version no longer contains the passage, the
    comment is kept and marked outdated rather than lost.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        SENT = "sent", "Sent to the agents"
        RESOLVED = "resolved", "Resolved"

    workspace = models.ForeignKey(ArticleWorkspace, on_delete=models.CASCADE, related_name="comments")
    version = models.ForeignKey(ArticleVersion, on_delete=models.CASCADE, related_name="comments")
    anchored_version = models.ForeignKey(ArticleVersion, on_delete=models.CASCADE, related_name="+")
    block_id = models.CharField(max_length=64)
    start = models.PositiveIntegerField()
    end = models.PositiveIntegerField()
    quote = models.TextField()
    prefix = models.CharField(max_length=100, blank=True)
    suffix = models.CharField(max_length=100, blank=True)
    comment = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    outdated = models.BooleanField(default=False, help_text="The passage changed or was removed in a later version")
    sent_with = models.ForeignKey(
        SessionMessage, null=True, blank=True, on_delete=models.SET_NULL, related_name="comments"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"“{Truncator(self.quote).chars(40)}”: {Truncator(self.comment).chars(60)}"

    def save(self, *args, **kwargs):
        if self.anchored_version_id is None:
            self.anchored_version_id = self.version_id
        super().save(*args, **kwargs)

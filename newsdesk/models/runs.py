"""Pipeline runs and their steps: the log of what each agent did, and what it cost."""

from decimal import Decimal

from django.conf import settings
from django.db import models


class Usage(models.Model):
    """Token usage and estimated cost, summed per step and per run."""

    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    web_searches = models.PositiveIntegerField(default=0)
    cost = models.DecimalField("estimated cost (US$)", max_digits=10, decimal_places=4, default=Decimal("0"))

    USAGE_FIELDS = ["input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "web_searches", "cost"]

    class Meta:
        abstract = True

    def add_usage(self, other):
        for field in self.USAGE_FIELDS:
            setattr(self, field, getattr(self, field) + getattr(other, field))

    @property
    def total_tokens(self):
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens


class AgentRun(Usage):
    """One job on one article: a first draft, a regeneration or a revision."""

    class Kind(models.TextChoices):
        GENERATE = "generate", "Generate"
        REVISE = "revise", "Revise"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Finished"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    ACTIVE = [Status.QUEUED, Status.RUNNING]

    workspace = models.ForeignKey("newsdesk.ArticleWorkspace", on_delete=models.CASCADE, related_name="runs")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.GENERATE)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    trigger = models.ForeignKey(
        "newsdesk.SessionMessage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    plan = models.JSONField(default=list, blank=True, help_text="The orchestrator's plan: steps and instructions")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    celery_task_id = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            # One run at a time per article: a second Generate or feedback waits its turn.
            models.UniqueConstraint(
                fields=["workspace"],
                condition=models.Q(status__in=["queued", "running"]),
                name="one_active_run_per_workspace",
            )
        ]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.pk} ({self.get_status_display()})"

    @property
    def is_active(self):
        return self.status in self.ACTIVE

    @property
    def duration(self):
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return None


class AgentStep(Usage):
    class Status(models.TextChoices):
        PENDING = "pending", "Waiting"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Done"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="steps")
    sequence = models.PositiveSmallIntegerField()
    role = models.CharField(max_length=20)
    agent = models.ForeignKey(
        "newsdesk.AgentDefinition", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    model = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    instructions = models.TextField(blank=True, help_text="What the orchestrator asked this agent to do")
    input_summary = models.TextField(blank=True)
    output = models.JSONField(null=True, blank=True)
    summary = models.TextField(blank=True, help_text="Readable summary of the output")
    error = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["run", "sequence"]
        constraints = [models.UniqueConstraint(fields=["run", "sequence"], name="unique_step_sequence")]

    def __str__(self):
        return f"{self.role} ({self.get_status_display()})"

    @property
    def duration(self):
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return None


class AgentEvent(models.Model):
    """A line in the live activity feed. Persisted so the feed can be replayed."""

    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="events")
    step = models.ForeignKey(AgentStep, null=True, blank=True, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=20)
    message = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.kind}: {self.message[:60]}"

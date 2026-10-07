"""Topics: what the newsroom wants to write about. One topic, one or more articles."""

from django.conf import settings
from django.db import models
from django.utils.text import Truncator
from wagtail.admin.panels import FieldPanel


class Topic(models.Model):
    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Suggested"
        ACCEPTED = "accepted", "Accepted"
        IN_PROGRESS = "in_progress", "In progress"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"
        REJECTED = "rejected", "Rejected"

    class Origin(models.TextChoices):
        HUMAN = "human", "Editor"
        AGENT = "agent", "Topic scout"

    title = models.CharField(max_length=200)
    desk = models.ForeignKey(
        "newsdesk.DeskAgent",
        on_delete=models.PROTECT,
        related_name="topics",
        verbose_name="section",
        help_text="The section (desk) this topic belongs to",
    )
    description = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACCEPTED)
    origin = models.CharField(max_length=6, choices=Origin.choices, default=Origin.HUMAN, editable=False)
    scout_notes = models.TextField(
        blank=True, editable=False, help_text="Why the scout suggested this topic, with links"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    panels = [FieldPanel("title"), FieldPanel("desk"), FieldPanel("description"), FieldPanel("status")]

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return Truncator(self.title).chars(80)

    def article_started(self):
        """A workspace was opened for this topic."""
        if self.status in (self.Status.SUGGESTED, self.Status.ACCEPTED):
            self.status = self.Status.IN_PROGRESS
            self.save(update_fields=["status", "updated_at"])

    def article_published(self):
        if self.status != self.Status.PUBLISHED:
            self.status = self.Status.PUBLISHED
            self.save(update_fields=["status", "updated_at"])

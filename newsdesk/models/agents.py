"""Editable agent configuration: one AgentDefinition per pipeline role, model prices
for cost estimates, and the newsroom-wide AI settings (house style, limits).

Everything here is data so editors can change prompts, models and the house
style in the admin without a code change. Starter values live in
newsdesk/roles.py and are created by bootstrap_site.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.contrib.settings.models import BaseGenericSetting, register_setting

EFFORT_LEVELS = [
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
    ("xhigh", "Extra high"),
    ("max", "Max"),
]


class AgentRole(models.TextChoices):
    ORCHESTRATOR = "orchestrator", "Orchestrator"
    RESEARCHER = "researcher", "Researcher"
    ANALYST = "analyst", "Analyst"
    OUTLINER = "outliner", "Outliner"
    WRITER = "writer", "Writer"
    FACT_CHECKER = "fact_checker", "Fact-checker"
    EDITOR = "editor", "Editor"
    SEO = "seo", "Headline & SEO"
    SUMMARISER = "summariser", "Session summariser"
    SCOUT = "scout", "Topic scout"


# The pipeline cannot run without these, so they cannot be switched off.
REQUIRED_ROLES = {AgentRole.ORCHESTRATOR, AgentRole.WRITER, AgentRole.FACT_CHECKER, AgentRole.SUMMARISER}


class AgentDefinition(models.Model):
    role = models.CharField(max_length=20, choices=AgentRole.choices, unique=True)
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True, help_text="What this agent does (shown in the activity log)")
    system_prompt = models.TextField(
        help_text="The agent's standing instructions. The house style and the section's guidelines are "
        "added automatically for agents that write or edit copy."
    )
    model = models.CharField(
        max_length=80,
        default="claude-opus-5-5",
        help_text="Claude model ID, e.g. claude-opus-5-5 or claude-sonnet-5-5",
    )
    effort = models.CharField(
        max_length=10,
        choices=EFFORT_LEVELS,
        default="high",
        help_text="How hard the model thinks. Higher is slower and costs more. (Current Claude models "
        "do not accept a temperature setting; effort is the control.)",
    )
    max_tokens = models.PositiveIntegerField(default=32000, help_text="Upper limit on one response")
    web_search = models.BooleanField(default=False, help_text="May search the web")
    web_fetch = models.BooleanField(default=False, help_text="May read web pages it found or was given")
    max_web_uses = models.PositiveSmallIntegerField(default=8, help_text="Searches/page reads per step")
    active = models.BooleanField(default=True, help_text="Untick to skip this agent (optional roles only)")
    # Set when an editor changes the agent in the admin; bootstrap_site then
    # stops refreshing it with newer starter prompts.
    customised = models.BooleanField(default=False, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    panels = [
        MultiFieldPanel([FieldPanel("name"), FieldPanel("description"), FieldPanel("active")], heading="Agent"),
        FieldPanel("system_prompt"),
        MultiFieldPanel([FieldPanel("model"), FieldPanel("effort"), FieldPanel("max_tokens")], heading="Model"),
        MultiFieldPanel(
            [FieldPanel("web_search"), FieldPanel("web_fetch"), FieldPanel("max_web_uses")], heading="Tools"
        ),
    ]

    class Meta:
        ordering = ["pk"]
        verbose_name = "agent"

    def __str__(self):
        return self.name

    @property
    def required(self):
        return self.role in REQUIRED_ROLES

    def clean(self):
        if not self.active and self.role in REQUIRED_ROLES:
            raise ValidationError({"active": "The pipeline needs this agent; it cannot be switched off."})

    @classmethod
    def for_role(cls, role):
        return cls.objects.get(role=role)


class ModelPrice(models.Model):
    """US$ per million tokens, used for cost estimates (not billing)."""

    model = models.CharField(max_length=80, unique=True)
    input_per_mtok = models.DecimalField(max_digits=8, decimal_places=4)
    output_per_mtok = models.DecimalField(max_digits=8, decimal_places=4)
    cache_write_per_mtok = models.DecimalField(max_digits=8, decimal_places=4)
    cache_read_per_mtok = models.DecimalField(max_digits=8, decimal_places=4)

    class Meta:
        ordering = ["model"]
        verbose_name = "model price"

    def __str__(self):
        return self.model

    def cost(self, input_tokens=0, output_tokens=0, cache_write_tokens=0, cache_read_tokens=0):
        million = Decimal(1_000_000)
        return (
            Decimal(input_tokens) * self.input_per_mtok
            + Decimal(output_tokens) * self.output_per_mtok
            + Decimal(cache_write_tokens) * self.cache_write_per_mtok
            + Decimal(cache_read_tokens) * self.cache_read_per_mtok
        ) / million


def default_house_style():
    from newsdesk.roles import DEFAULT_HOUSE_STYLE

    return DEFAULT_HOUSE_STYLE


@register_setting(icon="cogs")
class NewsroomAISettings(BaseGenericSetting):
    house_style = models.TextField(
        default=default_house_style,
        help_text="The newspaper's style guide. Every agent that writes, edits or checks copy follows it; "
        "each section's own guidelines are added after it.",
    )
    web_search_cost_per_1000 = models.DecimalField(
        "web search cost per 1,000 searches (US$)", max_digits=8, decimal_places=2, default=Decimal("10.00")
    )
    summarise_after_tokens = models.PositiveIntegerField(
        default=30000,
        help_text="When an article's conversation grows past this (estimated tokens), older turns are "
        "summarised. The brief, latest draft, sources and open feedback are always kept word for word.",
    )
    keep_recent_messages = models.PositiveSmallIntegerField(
        default=10, help_text="Most recent conversation turns always kept word for word"
    )
    max_fix_rounds = models.PositiveSmallIntegerField(
        default=2,
        help_text="How many times the orchestrator may send a draft back to fix serious fact-check "
        "flags before handing it to you",
    )

    panels = [
        FieldPanel("house_style"),
        MultiFieldPanel(
            [FieldPanel("summarise_after_tokens"), FieldPanel("keep_recent_messages"), FieldPanel("max_fix_rounds")],
            heading="Pipeline",
        ),
        FieldPanel("web_search_cost_per_1000"),
    ]

    class Meta:
        verbose_name = "AI newsroom settings"

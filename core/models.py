import logging

from django import forms
from django.db import models
from django.template.loader import render_to_string
from modelcluster.fields import ParentalKey
from wagtail.admin.mail import send_mail
from wagtail.admin.panels import FieldPanel, FieldRowPanel, InlinePanel, MultiFieldPanel
from wagtail.contrib.forms.models import AbstractEmailForm, AbstractFormField
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting
from wagtail.fields import RichTextField, StreamField
from wagtail.models import Page
from wagtail.search import index

from .blocks import StandardPageBodyBlock

logger = logging.getLogger(__name__)


class StandardPage(Page):
    """Simple content page: About, AI policy, Terms, Privacy, Contact…"""

    intro = models.TextField(blank=True)
    body = StreamField(StandardPageBodyBlock(), blank=True)

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

    # Publisher details: shown on Contact, Terms, Privacy and the grievance
    # page, and required before launch (IT Rules 2021, DPDP Act 2023).
    legal_name = models.CharField(
        max_length=200, blank=True, help_text="The company or LLP that publishes the site, as registered"
    )
    registered_address = models.TextField(blank=True, help_text="Registered office: full postal address in India")
    contact_email = models.EmailField(blank=True, help_text="General enquiries")
    contact_phone = models.CharField(max_length=40, blank=True)
    corrections_email = models.EmailField(blank=True, help_text="Where readers report errors; blank uses the contact email")
    privacy_email = models.EmailField(
        blank=True, help_text="Who answers questions about personal data; blank uses the grievance email"
    )
    grievance_officer_name = models.CharField(max_length=120, blank=True, help_text="Must live in India")
    grievance_officer_designation = models.CharField(max_length=120, blank=True, default="Grievance Officer")
    grievance_email = models.EmailField(blank=True, help_text="Complaints from the form are sent here")
    grievance_phone = models.CharField(max_length=40, blank=True)
    self_regulatory_body = models.CharField(
        max_length=200, blank=True, help_text="The self-regulating body the publisher belongs to (IT Rules 2021, rule 12)"
    )
    self_regulatory_body_url = models.URLField(blank=True)

    panels = [
        MultiFieldPanel(
            [FieldPanel("site_name"), FieldPanel("tagline"), FieldPanel("publication_language")],
            heading="Publication",
        ),
        MultiFieldPanel(
            [FieldPanel("twitter_handle"), FieldPanel("default_share_image")], heading="Social"
        ),
        MultiFieldPanel(
            [
                FieldPanel("legal_name"),
                FieldPanel("registered_address"),
                FieldPanel("contact_email"),
                FieldPanel("contact_phone"),
                FieldPanel("corrections_email"),
                FieldPanel("privacy_email"),
            ],
            heading="Publisher details",
        ),
        MultiFieldPanel(
            [
                FieldPanel("grievance_officer_name"),
                FieldPanel("grievance_officer_designation"),
                FieldPanel("grievance_email"),
                FieldPanel("grievance_phone"),
                FieldPanel("self_regulatory_body"),
                FieldPanel("self_regulatory_body_url"),
            ],
            heading="Grievance redressal",
        ),
        FieldPanel("demo_notice"),
    ]

    @property
    def corrections_address(self):
        return self.corrections_email or self.contact_email

    @property
    def privacy_address(self):
        return self.privacy_email or self.grievance_email

    class Meta:
        verbose_name = "site settings"


class GrievanceFormField(AbstractFormField):
    page = ParentalKey("GrievanceFormPage", on_delete=models.CASCADE, related_name="form_fields")


# Hidden from people, filled in by spam bots: such submissions are dropped.
HONEYPOT_FIELD = "website"


class GrievanceFormPage(AbstractEmailForm):
    """Complaints to the Grievance Officer (IT Rules 2021, Part III).

    Every complaint is stored (Forms in the admin), emailed to the grievance
    address in Site settings and acknowledged to the complainant with a
    reference number.
    """

    intro = RichTextField(blank=True)
    thank_you_text = RichTextField(blank=True)

    content_panels = AbstractEmailForm.content_panels + [
        FieldPanel("intro"),
        InlinePanel("form_fields", label="Form fields"),
        FieldPanel("thank_you_text"),
        MultiFieldPanel(
            [FieldRowPanel([FieldPanel("from_address"), FieldPanel("to_address")]), FieldPanel("subject")],
            heading="Email",
            help_text="Complaints go to the grievance email in Site settings; ‘To address’ is only a fallback.",
        ),
    ]

    parent_page_types = ["news.HomePage"]
    subpage_types = []
    max_count = 1

    search_fields = Page.search_fields + [index.SearchField("intro")]

    @staticmethod
    def reference(submission):
        return f"G-{submission.pk:05d}"

    def site_settings(self):
        return SiteSettings.for_site(self.get_site())

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context["contact_value"] = {"kind": "grievance"}
        return context

    def render_landing_page(self, request, form_submission=None, *args, **kwargs):
        response = super().render_landing_page(request, form_submission, *args, **kwargs)
        response.context_data["reference"] = self.reference(form_submission) if form_submission else ""
        return response

    def get_form(self, *args, **kwargs):
        form = super().get_form(*args, **kwargs)
        form.fields[HONEYPOT_FIELD] = forms.CharField(
            required=False, label="Leave this empty", widget=forms.TextInput(attrs={"autocomplete": "off", "tabindex": "-1"})
        )
        return form

    def _send(self, subject, body, to, reply_to=None):
        # The complaint is already saved: a mail outage must not lose it or
        # show the complainant an error.
        try:
            send_mail(subject, body, [to], self.from_address, reply_to=[reply_to] if reply_to else None)
        except Exception:
            logger.exception("Could not send email: %s", subject)  # no address: logs reach Sentry

    def process_form_submission(self, form):
        if form.cleaned_data.pop(HONEYPOT_FIELD, ""):
            return None
        submission = self.get_submission_class().objects.create(form_data=form.cleaned_data, page=self)
        settings = self.site_settings()
        reference = self.reference(submission)
        context = {"page": self, "settings": settings, "reference": reference}
        officer = settings.grievance_email or self.to_address
        if officer:
            self._send(f"{self.subject or 'New complaint'} [{reference}]", self.render_email(form), officer)
        else:
            logger.error("Complaint %s received but no grievance email is set", reference)
        complainant = next(
            (form.cleaned_data[f.clean_name] for f in self.get_form_fields() if f.field_type == "email"), ""
        )
        if complainant:
            body = render_to_string("core/emails/grievance_acknowledgement.txt", context)
            self._send(f"We have received your complaint ({reference})", body, complainant, reply_to=officer)
        return submission

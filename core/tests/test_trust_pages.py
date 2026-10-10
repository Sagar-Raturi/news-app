"""About/policy/contact pages, the grievance form, corrections and the launch checklist."""

import datetime
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from wagtail.contrib.forms.models import FormSubmission

from core.launch import launch_checks
from core.models import GrievanceFormPage, SiteSettings, StandardPage
from core.newsroom import bootstrap
from core.trust_pages import STANDARD_PAGES, TRUST_PAGE_SLUGS
from news.models import ArticleCorrection, SectionPage
from news.tests.utils import make_article

PUBLISHER = {
    "legal_name": "Manthan Media Private Limited",
    "registered_address": "12 Example Road\nNew Delhi 110001",
    "contact_email": "hello@ledger.test",
    "grievance_officer_name": "R. Sharma",
    "grievance_email": "grievance@ledger.test",
}


class TrustPagesTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        with cls.captureOnCommitCallbacks(execute=True):
            cls.site = bootstrap()
        cls.pages = cls.site["trust_pages"]

    def set_publisher(self, **overrides):
        settings = SiteSettings.for_site(self.site["home"].get_site())
        for field, value in {**PUBLISHER, **overrides}.items():
            setattr(settings, field, value)
        settings.save()
        return settings

    def publish(self, *slugs):
        for slug in slugs:
            self.pages[slug].specific.save_revision().publish()


class BootstrapTrustPagesTests(TrustPagesTestCase):
    def test_pages_created_as_drafts_with_launch_text(self):
        self.assertEqual(set(self.pages), set(TRUST_PAGE_SLUGS.values()))
        for spec in STANDARD_PAGES:
            page = StandardPage.objects.get(slug=spec["slug"])
            self.assertFalse(page.live, spec["slug"])
            self.assertEqual(page.title, spec["title"])
            self.assertTrue(page.body, spec["slug"])
            self.assertIsNotNone(page.latest_revision, spec["slug"])
        self.assertFalse(GrievanceFormPage.objects.get().live)
        # Unpublished pages aren't reachable or linked.
        self.assertEqual(self.client.get("/terms/").status_code, 404)
        self.assertNotContains(self.client.get("/"), 'href="/terms/"')

    def test_existing_pages_are_left_alone(self):
        terms = StandardPage.objects.get(slug="terms")
        terms.title = "Our terms"
        terms.save_revision().publish()
        bootstrap()
        self.assertEqual(StandardPage.objects.get(slug="terms").title, "Our terms")
        self.assertEqual(StandardPage.objects.filter(slug="terms").count(), 1)
        self.assertEqual(GrievanceFormPage.objects.count(), 1)

    def test_grievance_form_fields(self):
        form = GrievanceFormPage.objects.get().get_form()
        choices = [label for _, label in form.fields["what_is_your_complaint_about"].choices]
        self.assertEqual(len(choices), 6)
        self.assertIn("Defamation", choices)
        self.assertTrue(form.fields["email_address"].required)
        self.assertFalse(form.fields["phone_number"].required)


class PublishedPagesTests(TrustPagesTestCase):
    def test_footer_links_live_pages(self):
        self.publish("terms", "privacy", "contact")
        response = self.client.get("/")
        for slug in ["terms", "privacy", "contact"]:
            self.assertContains(response, f'href="/{slug}/"')
        self.assertNotContains(response, 'href="/grievances/"')

    def test_contact_details_come_from_site_settings(self):
        self.set_publisher(contact_phone="+91 11 0000 0000", self_regulatory_body="News Council (example)")
        self.publish("contact")
        response = self.client.get("/contact/")
        self.assertContains(response, "Manthan Media Private Limited")
        self.assertContains(response, "12 Example Road<br>New Delhi 110001")
        self.assertContains(response, "+91 11 0000 0000")
        self.assertContains(response, "R. Sharma")
        self.assertContains(response, "mailto:grievance@ledger.test")
        self.assertContains(response, "you can appeal to News Council (example)")
        # Corrections and privacy fall back to the contact and grievance addresses.
        self.assertContains(response, "Report an error</dt><dd><a href=\"mailto:hello@ledger.test\"", html=False)
        self.assertContains(response, "Personal data questions</dt><dd><a href=\"mailto:grievance@ledger.test\"", html=False)

    def test_missing_details_are_hidden_from_readers(self):
        self.publish("contact")
        response = self.client.get("/contact/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Registered office")
        self.assertNotContains(response, "Not shown to readers yet")

    def test_policy_pages_render(self):
        self.set_publisher()
        self.publish(*TRUST_PAGE_SLUGS.values())
        for slug in TRUST_PAGE_SLUGS.values():
            with self.subTest(slug=slug):
                response = self.client.get(f"/{slug}/")
                self.assertEqual(response.status_code, 200)
        self.assertContains(self.client.get("/privacy/"), "Data Protection Board of India")
        self.assertContains(self.client.get("/terms/"), "governed by the laws of India")


class GrievanceFormTests(TrustPagesTestCase):
    def setUp(self):
        self.set_publisher()
        self.publish("grievances")
        self.page = GrievanceFormPage.objects.get()

    def complaint(self, **extra):
        data = {}
        for field in self.page.get_form_fields():
            data[field.clean_name] = {
                "email": "reader@example.com",
                "url": "https://ledger.test/politics/some-article/",
                "dropdown": "A factual error",
                "checkbox": "on",
            }.get(field.field_type, "Asha Reader" if field.field_type == "singleline" else "The date is wrong.")
        data.update(extra)
        return data

    def test_submission_is_stored_sent_and_acknowledged(self):
        response = self.client.post("/grievances/", self.complaint())
        self.assertEqual(response.status_code, 200)
        submission = FormSubmission.objects.get()
        reference = GrievanceFormPage.reference(submission)
        self.assertContains(response, reference)
        self.assertNotIn("website", submission.get_data())

        officer, receipt = mail.outbox
        self.assertEqual(officer.to, ["grievance@ledger.test"])
        self.assertIn(reference, officer.subject)
        self.assertIn("The date is wrong.", officer.body)
        self.assertEqual(receipt.to, ["reader@example.com"])
        self.assertEqual(receipt.reply_to, ["grievance@ledger.test"])
        self.assertIn(reference, receipt.body)
        self.assertIn("within 15 days", receipt.body)
        self.assertIn("Manthan Media Private Limited", receipt.body)

    def test_spam_trap_drops_the_submission(self):
        response = self.client.post("/grievances/", self.complaint(website="http://spam.example"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FormSubmission.objects.exists())
        self.assertEqual(mail.outbox, [])

    def test_required_fields(self):
        response = self.client.post("/grievances/", {})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        self.assertFalse(FormSubmission.objects.exists())

    def test_mail_failure_keeps_the_complaint(self):
        with mock.patch("core.models.send_mail", side_effect=OSError("SMTP down")):
            with self.assertLogs("core.models", "ERROR") as logs:
                response = self.client.post("/grievances/", self.complaint())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FormSubmission.objects.count(), 1)
        self.assertNotIn("reader@example.com", "\n".join(logs.output))


class CorrectionsTests(TrustPagesTestCase):
    def test_correction_note_on_article_and_corrections_page(self):
        section = SectionPage.objects.get(slug="politics")
        article = make_article(section, title="Bill passes Lok Sabha")
        article.corrections.add(
            ArticleCorrection(date=datetime.date(2026, 10, 2), note="An earlier version gave the wrong date.")
        )
        article.save_revision().publish()
        hidden = make_article(section, title="Withdrawn story", live=False)
        hidden.corrections.add(ArticleCorrection(note="Not public."))
        hidden.save()
        self.publish("corrections")

        response = self.client.get(article.url)
        self.assertContains(response, "Corrected 2 October 2026")
        self.assertContains(response, "An earlier version gave the wrong date.")
        self.assertContains(response, 'href="/corrections/">Our corrections policy')

        page = self.client.get("/corrections/")
        self.assertContains(page, "Bill passes Lok Sabha")
        self.assertContains(page, "An earlier version gave the wrong date.")
        self.assertNotContains(page, "Not public.")

    def test_article_without_corrections(self):
        article = make_article(SectionPage.objects.get(slug="economy"), title="Plain story")
        response = self.client.get(article.url)
        self.assertNotContains(response, 'id="corrections"')
        self.assertNotContains(response, "Corrected ")


class LaunchChecklistTests(TrustPagesTestCase):
    def failing(self):
        return {check.label for check in launch_checks() if not check.ok}

    def test_fresh_site_lists_everything_missing(self):
        missing = self.failing()
        self.assertIn("Publisher details: legal name, registered address and contact email", missing)
        self.assertIn("Grievance Officer: name and email", missing)
        self.assertIn("‘Terms of use’ page published", missing)
        self.assertIn("At least one article published", missing)

    def test_filled_in_site_passes(self):
        self.set_publisher(self_regulatory_body="News Council (example)")
        self.publish(*TRUST_PAGE_SLUGS.values())
        make_article(SectionPage.objects.get(slug="economy"), title="Launch story")
        with self.settings(NEWSDESK_WRITER="fake"):
            self.assertEqual(self.failing(), set())
            out = StringIO()
            call_command("launch_check", stdout=out)
        self.assertIn("Ready to launch.", out.getvalue())

    def test_demo_logins_are_flagged(self):
        get_user_model().objects.create_user("editor", "editor@example.com", "editor")
        self.assertIn("No demo logins", self.failing())

    def test_command_fails_while_items_missing(self):
        with self.assertRaises(SystemExit) as exit:
            call_command("launch_check", stdout=StringIO())
        self.assertEqual(exit.exception.code, 1)

    def test_dashboard_panel_for_admins(self):
        admin = get_user_model().objects.create_superuser("chief", "chief@ledger.test", "pw-123456789")
        self.client.force_login(admin)
        response = self.client.get("/admin/")
        self.assertContains(response, "Before launch:")
        self.assertContains(response, "Grievance Officer: name and email")

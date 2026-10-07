from unittest import mock

from django.test import override_settings
from django.urls import reverse
from wagtail.models import WorkflowState

from news.models import ArticlePage
from newsdesk.models import ArticleNote, DeskFeedback, DraftRequest
from newsdesk.prompts import article_as_text, build_system, build_user_message
from newsdesk.publishing import apply_revision
from newsdesk.schema import DraftSource
from newsdesk.tasks import draft_article
from newsdesk.views import can_revise, latest_review_comment
from newsdesk.writer import AnthropicWriter, DraftResult

from .test_newsdesk import MATERIAL, NewsdeskTestCase, block, fake_response, make_draft


@override_settings(NEWSDESK_WRITER="fake")
class RevisionTestCase(NewsdeskTestCase):
    def setUp(self):
        self.original = self.make_request(article_type="explainer")
        draft_article(self.original.pk)
        self.original.refresh_from_db()
        self.article = self.original.article.specific

    def request_changes(self, comment="Lead with what households pay."):
        state = self.article.current_workflow_state
        task_state = state.current_task_state
        task_state.task.specific.on_action(task_state, self.editor, "reject", comment=comment)
        self.article.refresh_from_db()

    def make_revision(self, instructions="Lead with what households pay.", user=None):
        return DraftRequest.objects.create(
            desk=self.original.desk,
            article_type=self.original.article_type,
            brief=self.original.brief,
            source_material=self.original.source_material,
            revision_of=self.original,
            article=self.article,
            instructions=instructions,
            requested_by=user or self.editor,
        )


class RevisionPromptTests(RevisionTestCase):
    def test_prompt_carries_instructions_and_latest_text(self):
        # A manual edit saved as a draft revision must reach the agent.
        latest = self.article.get_latest_revision_as_object()
        latest.standfirst = "Edited by hand before revision."
        latest.save_revision(user=self.editor)

        message = build_user_message(self.make_revision())
        self.assertIn("<editor_instructions>\nLead with what households pay.\n</editor_instructions>", message)
        self.assertIn("Standfirst: Edited by hand before revision.", message)
        self.assertIn(f"Headline: {self.article.title}", message)
        self.assertIn(MATERIAL, message)
        self.assertIn("complete revised article", message)

    def test_revision_prompt_remembers_earlier_notes_for_this_article(self):
        ArticleNote.remember(self.article, "Keep it under 600 words.", ArticleNote.Source.COMMISSION)
        self.request_changes("Lead with what households pay.")
        ArticleNote.objects.create(article=self.article, note="Forgotten note.", active=False)

        message = build_user_message(self.make_revision("Lead with what households pay."))
        self.assertIn("<article_notes>\n- Keep it under 600 words.\n</article_notes>", message)
        # The current instructions appear once, as instructions, not again as a note.
        self.assertEqual(message.count("Lead with what households pay."), 1)
        self.assertNotIn("Forgotten note.", message)
        # Article notes never reach the desk's (cached) system prompt.
        self.assertNotIn("600 words", build_system(self.economy, "explainer")[1]["text"])

    def test_revision_prompt_without_notes_has_no_notes_block(self):
        self.assertNotIn("<article_notes>", build_user_message(self.make_revision()))

    def test_article_text_keeps_paragraphs_and_blocks(self):
        result = DraftResult(
            make_draft(body=[block("paragraph", "One.\n\nTwo."), block("qa", "Why?", "Because."), block("stat", "30%", "Rise", source="Agmarknet")]),
            "m",
        )
        revision = self.make_revision()
        apply_revision(revision, result)
        text = article_as_text(self.article)
        self.assertIn("One.\n\nTwo.", text)
        self.assertIn("Q: Why?\nA: Because.", text)
        self.assertIn("[Key figure] 30% — Rise (source: Agmarknet)", text)

    def test_anthropic_writer_sends_revision_prompt(self):
        client = mock.MagicMock()
        client.beta.messages.parse.return_value = fake_response(make_draft())
        AnthropicWriter(client=client).write(self.make_revision())
        content = client.beta.messages.parse.call_args.kwargs["messages"][0]["content"]
        self.assertIn("<current_draft>", content)
        self.assertIn("Lead with what households pay.", content)


class ApplyRevisionTests(RevisionTestCase):
    def test_after_request_changes_review_resumes_on_new_text(self):
        self.request_changes()
        self.assertEqual(self.article.current_workflow_state.status, WorkflowState.STATUS_NEEDS_CHANGES)
        slug, authors = self.article.slug, self.article.authors

        result = DraftResult(make_draft(headline="Revised headline", body=[block("paragraph", "Households pay more.")]), "m")
        apply_revision(self.make_revision(), result)

        article = ArticlePage.objects.get(pk=self.article.pk)
        latest = article.get_latest_revision_as_object()
        self.assertEqual(latest.title, "Revised headline")
        self.assertEqual(latest.body[0].value.source, "<p>Households pay more.</p>")
        self.assertEqual((article.slug, article.authors), (slug, authors))
        self.assertFalse(article.live)
        state = article.current_workflow_state
        self.assertEqual(state.status, WorkflowState.STATUS_IN_PROGRESS)
        self.assertEqual(state.current_task_state.revision_id, article.latest_revision_id)
        self.assertEqual(ArticlePage.objects.count(), 1)

    def test_open_review_restarts_on_new_text(self):
        old_state = self.article.current_workflow_state
        apply_revision(self.make_revision(), DraftResult(make_draft(headline="Second take"), "m"))
        article = ArticlePage.objects.get(pk=self.article.pk)
        old_state.refresh_from_db()
        self.assertEqual(old_state.status, WorkflowState.STATUS_CANCELLED)
        self.assertEqual(article.current_workflow_state.current_task_state.revision_id, article.latest_revision_id)

    def test_links_must_come_from_material_or_instructions(self):
        draft = make_draft(
            sources=[
                DraftSource(title="Bulletin", publisher="MoHFW", url="https://mohfw.gov.in/"),
                DraftSource(title="Invented", publisher="X", url="https://example.com/fake"),
            ]
        )
        apply_revision(self.make_revision("Cite the ministry: https://mohfw.gov.in/"), DraftResult(draft, "m"))
        latest = ArticlePage.objects.get(pk=self.article.pk).get_latest_revision_as_object()
        self.assertEqual([s.value["url"] for s in latest.sources], ["https://mohfw.gov.in/", ""])

    def test_published_articles_are_not_rewritten(self):
        self.article.save_revision(user=self.editor).publish(user=self.editor)
        with self.assertRaisesMessage(ValueError, "already published"):
            apply_revision(self.make_revision(), DraftResult(make_draft(), "m"))


class RevisionTaskTests(RevisionTestCase):
    def test_task_revises_in_place(self):
        self.request_changes()
        revision = self.make_revision()
        self.assertEqual(draft_article(revision.pk), DraftRequest.Status.DONE)
        revision.refresh_from_db()
        self.assertEqual(revision.article_id, self.article.pk)
        latest = ArticlePage.objects.get(pk=self.article.pk).get_latest_revision_as_object()
        self.assertIn("[Demo revision]", latest.body[0].value.source)
        self.assertEqual(ArticlePage.objects.count(), 1)

    def test_fake_writer_shows_earlier_notes(self):
        ArticleNote.remember(self.article, "Keep it under 600 words.", ArticleNote.Source.COMMISSION)
        revision = self.make_revision("Shorter, please.")
        draft_article(revision.pk)
        body = ArticlePage.objects.get(pk=self.article.pk).get_latest_revision_as_object().body
        self.assertIn("asked: Shorter, please.", body[0].value.source)
        self.assertIn("also followed: Keep it under 600 words.", body[1].value.source)

    def test_review_comments_still_recorded_with_revisions(self):
        self.make_revision()
        self.request_changes("Name the regulator.")
        note = ArticleNote.objects.get(note="Name the regulator.")
        self.assertEqual(note.article_id, self.article.pk)
        self.assertFalse(DeskFeedback.objects.exists())


class ReviseViewTests(RevisionTestCase):
    def url(self, page=None):
        return reverse("newsdesk_revise", args=[(page or self.article).pk])

    def test_form_prefilled_with_latest_review_comment(self):
        self.request_changes("Lead with what households pay.")
        self.assertEqual(latest_review_comment(self.article), "Lead with what households pay.")
        self.client.force_login(self.editor)
        response = self.client.get(self.url())
        self.assertContains(response, "Lead with what households pay.")
        self.assertContains(response, "Economy desk")

    def test_submit_creates_revision_and_queues_agent(self):
        self.request_changes()
        self.client.force_login(self.editor)
        with mock.patch("newsdesk.tasks.draft_article.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(self.url(), {"instructions": "Shorter, please."})
        self.assertRedirects(response, reverse("wagtailsnippets_newsdesk_draftrequest:list"))
        revision = DraftRequest.objects.get(revision_of=self.original)
        self.assertEqual((revision.article_id, revision.instructions, revision.requested_by), (self.article.pk, "Shorter, please.", self.editor))
        delay.assert_called_once_with(revision.pk)

    def test_writer_can_revise_own_draft_after_changes_requested(self):
        self.assertFalse(can_revise(self.article, self.writer))  # locked while in review
        self.request_changes()
        self.assertTrue(can_revise(ArticlePage.objects.get(pk=self.article.pk), self.writer))

    def test_not_for_human_articles_published_pages_or_while_busy(self):
        self.client.force_login(self.editor)
        human = ArticlePage(title="Human story", standfirst="s", body=[], live=False, owner=self.writer)
        self.economy.section.add_child(instance=human)
        # Wagtail turns PermissionDenied into a redirect to the dashboard.
        self.assertRedirects(self.client.get(self.url(human)), reverse("wagtailadmin_home"))

        self.make_revision()  # queued, not yet written
        response = self.client.get(self.url())
        self.assertRedirects(response, reverse("wagtailadmin_pages:edit", args=[self.article.pk]), fetch_redirect_response=False)

        DraftRequest.objects.update(status=DraftRequest.Status.DONE)
        self.article.save_revision(user=self.editor).publish(user=self.editor)
        self.assertRedirects(self.client.get(self.url()), reverse("wagtailadmin_home"))
        self.assertEqual(DraftRequest.objects.filter(revision_of=self.original).count(), 1)

    def test_buttons_on_edit_screen(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse("wagtailadmin_pages:edit", args=[self.article.pk]))
        self.assertContains(response, self.url())
        self.assertContains(response, "Revise with AI")

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from wagtail.models import GroupPagePermission, Workflow, WorkflowPage, WorkflowState
from wagtail.test.utils.form_data import inline_formset, nested_form_data, rich_text, streamfield

from core.newsroom import EDITORS, WORKFLOW_NAME, WRITERS, bootstrap
from news.models import ArticleAuthor, ArticlePage, Author, SectionPage

User = get_user_model()


class BootstrapTests(TestCase):
    def test_creates_tree_groups_and_workflow(self):
        result = bootstrap()
        home = result["home"]
        self.assertEqual(
            [s.slug for s in SectionPage.objects.child_of(home)],
            ["politics", "international", "local", "economy", "society",
             "education", "health", "science-tech", "opinion"],
        )
        self.assertEqual(result["about"].url, "/about/")
        self.assertTrue(Group.objects.filter(name=WRITERS).exists())
        self.assertTrue(Group.objects.filter(name=EDITORS).exists())
        self.assertFalse(Group.objects.filter(name="Moderators").exists())
        self.assertEqual(home.get_workflow().name, WORKFLOW_NAME)
        self.assertEqual(list(Workflow.objects.filter(active=True)), [result["workflow"]])

    def test_is_idempotent(self):
        call_command("bootstrap_site", verbosity=0)
        counts = (SectionPage.objects.count(), GroupPagePermission.objects.count(), WorkflowPage.objects.count())
        call_command("bootstrap_site", verbosity=0)
        self.assertEqual(
            counts,
            (SectionPage.objects.count(), GroupPagePermission.objects.count(), WorkflowPage.objects.count()),
        )


class NewsroomTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        result = bootstrap()
        cls.home = result["home"]
        cls.section = SectionPage.objects.get(slug="economy")
        cls.workflow = result["workflow"]
        cls.writer = User.objects.create_user("writer", "writer@example.com", "pass")
        cls.writer.groups.add(result["writers"])
        cls.editor = User.objects.create_user("editor", "editor@example.com", "pass")
        cls.editor.groups.add(result["editors"])
        cls.author = Author.objects.create(name="Asha Menon", slug="asha-menon")

    def make_draft(self, title="Draft story", user=None):
        article = ArticlePage(
            title=title,
            standfirst="Standfirst.",
            body=[{"type": "paragraph", "value": "<p>Body.</p>"}],
            live=False,
            owner=user or self.writer,
        )
        article.article_authors.add(ArticleAuthor(author=self.author))
        self.section.add_child(instance=article)
        article.save_revision(user=user or self.writer)
        return article


class PermissionTests(NewsroomTestCase):
    def test_writer_can_create_and_edit_but_not_publish(self):
        perms = self.section.permissions_for_user(self.writer)
        self.assertTrue(perms.can_add_subpage())
        article = self.make_draft()
        article_perms = article.permissions_for_user(self.writer)
        self.assertTrue(article_perms.can_edit())
        self.assertFalse(article_perms.can_publish())

    def test_writer_cannot_edit_or_delete_colleagues_drafts(self):
        colleague = User.objects.create_user("colleague", "c@example.com", "pass")
        colleague.groups.add(Group.objects.get(name=WRITERS))
        article = self.make_draft(user=colleague)
        perms = article.permissions_for_user(self.writer)
        self.assertFalse(perms.can_edit())
        self.assertFalse(perms.can_delete())
        self.assertTrue(article.permissions_for_user(self.editor).can_edit())

    def test_editor_can_publish(self):
        article = self.make_draft()
        self.assertTrue(article.permissions_for_user(self.editor).can_publish())

    def test_articles_inherit_newsroom_workflow(self):
        article = self.make_draft()
        self.assertEqual(article.get_workflow(), self.workflow)

    def test_only_editors_get_review_actions(self):
        article = self.make_draft()
        self.workflow.start(article, self.writer)
        task = self.workflow.tasks.first().specific
        self.assertEqual(task.get_actions(article, self.writer), [])
        self.assertIn("approve", [name for name, *_ in task.get_actions(article, self.editor)])


class PreviewTests(NewsroomTestCase):
    """Editors must be able to preview submissions (regression: tags FakeQuerySet)."""

    def test_editor_previews_draft_in_review(self):
        article = self.make_draft()
        article.tags.add("Inflation")
        article.save_revision(user=self.writer)
        state = self.workflow.start(article, self.writer)
        self.client.force_login(self.editor)
        response = self.client.get(reverse("wagtailadmin_pages:view_draft", args=(article.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Draft story")
        preview = self.client.get(
            reverse("wagtailadmin_pages:workflow_preview", args=(article.pk, state.current_task_state.task.pk))
        )
        self.assertEqual(preview.status_code, 200)


class WorkflowFlowTests(NewsroomTestCase):
    def test_submit_then_approve_publishes(self):
        article = self.make_draft()
        state = self.workflow.start(article, self.writer)
        self.assertEqual(state.status, WorkflowState.STATUS_IN_PROGRESS)
        self.assertFalse(ArticlePage.objects.get(pk=article.pk).live)

        task_state = state.current_task_state
        task_state.task.specific.on_action(task_state, self.editor, "approve")

        article.refresh_from_db()
        state.refresh_from_db()
        self.assertTrue(article.live)
        self.assertEqual(state.status, WorkflowState.STATUS_APPROVED)
        self.assertIsNotNone(article.published_date)

    def test_reject_sends_back_for_changes(self):
        article = self.make_draft()
        state = self.workflow.start(article, self.writer)
        task_state = state.current_task_state
        task_state.task.specific.on_action(task_state, self.editor, "reject")

        article.refresh_from_db()
        state.refresh_from_db()
        self.assertFalse(article.live)
        self.assertEqual(state.status, WorkflowState.STATUS_NEEDS_CHANGES)


class AdminWorkflowTests(NewsroomTestCase):
    """Drive the real Wagtail admin views as a writer and then an editor."""

    def article_form(self, action):
        return nested_form_data(
            {
                "title": "Onion prices climb again",
                "slug": "onion-prices-climb-again",
                "standfirst": "Why the kitchen staple keeps spiking.",
                "article_type": "news",
                "article_authors": inline_formset([{"author": self.author.pk}]),
                "hero_caption": "",
                "hero_credit": "",
                "body": streamfield([("paragraph", rich_text("<p>Prices rose sharply.</p>"))]),
                "sources": streamfield([]),
                "tags": "Inflation",
                "published_date": "",
                "ai_note": "",
                "corrections": inline_formset([]),
                action: "1",
            }
        )

    def test_writer_submits_editor_approves(self):
        self.client.force_login(self.writer)
        add_url = reverse("wagtailadmin_pages:add", args=("news", "articlepage", self.section.pk))
        response = self.client.post(add_url, self.article_form("action-submit"))
        self.assertEqual(response.status_code, 302)

        article = ArticlePage.objects.get(slug="onion-prices-climb-again")
        self.assertFalse(article.live)
        state = article.current_workflow_state
        self.assertIsNotNone(state)
        self.assertEqual(state.current_task_state.task.name, "Editor review")

        # Editors see it in their dashboard queue and approve it.
        self.client.force_login(self.editor)
        dashboard = self.client.get(reverse("wagtailadmin_home"))
        self.assertContains(dashboard, "Onion prices climb again")
        approve_url = reverse(
            "wagtailadmin_pages:workflow_action",
            args=(article.pk, "approve", state.current_task_state.pk),
        )
        response = self.client.post(approve_url, {"comment": "Good to go"})
        self.assertIn(response.status_code, (200, 302))

        article.refresh_from_db()
        self.assertTrue(article.live)

    def test_writer_cannot_publish_directly(self):
        self.client.force_login(self.writer)
        add_url = reverse("wagtailadmin_pages:add", args=("news", "articlepage", self.section.pk))
        self.client.post(add_url, self.article_form("action-publish"))
        article = ArticlePage.objects.get(slug="onion-prices-climb-again")
        self.assertFalse(article.live)

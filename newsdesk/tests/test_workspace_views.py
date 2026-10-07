from django.contrib.auth import get_user_model
from django.urls import reverse

from newsdesk.diff import diff_versions, word_diff
from newsdesk.models import AgentRun, ArticleWorkspace, FactCheckFlag, Source, Topic
from newsdesk.rendering import cite
from newsdesk.versions import restore_version

from .base import WorkspaceTestCase, heading, paragraph

User = get_user_model()


class ArticleListTests(WorkspaceTestCase):
    url = reverse("newsdesk_articles:index")

    def test_writers_and_editors_see_the_list(self):
        ws = self.make_workspace()
        for user in (self.writer, self.editor):
            self.client.force_login(user)
            response = self.client.get(self.url)
            self.assertContains(response, ws.title)
            self.assertContains(response, "New article")

    def test_filter_by_status(self):
        ready = self.make_workspace(self.make_topic("Ready one"))
        self.make_version(ready)
        ready.refresh_status()
        self.make_workspace(self.make_topic("Brief only"))
        self.client.force_login(self.editor)
        response = self.client.get(self.url + "?status=ready")
        self.assertContains(response, "Onion prices keep spiking")
        self.assertNotContains(response, "Brief only")

    def test_people_without_newsroom_access_are_kept_out(self):
        outsider = User.objects.create_user("reader", "r@example.com", "pass")
        self.client.force_login(outsider)
        self.assertNotEqual(self.client.get(self.url).status_code, 200)

    def test_menu_has_ai_articles_and_topics(self):
        self.client.force_login(self.writer)
        response = self.client.get(reverse("wagtailadmin_home"))
        self.assertContains(response, "AI articles")
        self.assertContains(response, "Topics")


class NewArticleTests(WorkspaceTestCase):
    url = reverse("newsdesk_articles:create")

    def post(self, **data):
        payload = {"article_type": "analysis", "brief": "Why do onion prices spike every autumn?"}
        payload.update(data)
        return self.client.post(self.url, payload)

    def test_new_topic_and_brief(self):
        self.client.force_login(self.writer)
        response = self.post(new_topic="Onion prices", desk=self.economy.pk, target_words="900", angle="Supply chains")
        ws = ArticleWorkspace.objects.get()
        self.assertRedirects(response, reverse("newsdesk_articles:detail", args=[ws.pk]) + "?tab=brief")
        self.assertEqual((ws.topic.title, ws.desk, ws.target_words, ws.created_by), ("Onion prices", self.economy, 900, self.writer))
        self.assertEqual(ws.topic.status, Topic.Status.IN_PROGRESS)
        self.assertEqual(ws.status, ArticleWorkspace.Status.BRIEF)

    def test_existing_topic_sets_the_section(self):
        topic = self.make_topic(desk=self.health)
        self.client.force_login(self.editor)
        self.assertContains(self.client.get(self.url + f"?topic={topic.pk}"), topic.title)
        self.post(topic=topic.pk, desk=self.economy.pk)
        self.assertEqual(ArticleWorkspace.objects.get().desk, self.health)

    def test_needs_a_topic_and_a_brief(self):
        self.client.force_login(self.editor)
        response = self.post(brief="")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pick a topic or name a new one.")
        self.assertFalse(ArticleWorkspace.objects.exists())

    def test_agents_do_not_write_opinion(self):
        self.client.force_login(self.editor)
        self.post(new_topic="A column", desk=self.economy.pk, article_type="opinion")
        self.assertFalse(ArticleWorkspace.objects.exists())


class WorkspacePageTests(WorkspaceTestCase):
    def setUp(self):
        self.ws = self.make_workspace()
        self.url = reverse("newsdesk_articles:detail", args=[self.ws.pk])

    def test_empty_workspace_shows_the_brief(self):
        self.client.force_login(self.writer)
        response = self.client.get(self.url)
        self.assertContains(response, "No draft yet")
        self.assertContains(response, "Save brief")
        self.assertContains(response, self.ws.brief)

    def test_draft_renders_blocks_citations_and_sources(self):
        Source.record(self.ws, url="https://agmarknet.gov.in/", title="Agmarknet", publisher="Government of India")
        version = self.make_version(
            self.ws, body=[paragraph("Prices rose 30% [S1] and more [S9]."), heading("What next")], source_numbers=[1]
        )
        self.client.force_login(self.writer)
        response = self.client.get(self.url)
        self.assertContains(response, f'data-block-id="{version.body[0]["id"]}"')
        self.assertContains(response, 'href="#source-1"')
        self.assertContains(response, "nd-cite--missing")
        self.assertContains(response, 'id="source-1"')
        self.assertContains(response, "https://agmarknet.gov.in/")

    def test_open_fact_check_flags_are_shown_above_the_draft(self):
        version = self.make_version(self.ws)
        FactCheckFlag.objects.create(
            workspace=self.ws, version=version, claim="30% in a month", severity="high", issue="Not in the research"
        )
        self.client.force_login(self.editor)
        response = self.client.get(self.url)
        self.assertContains(response, "1 open flag")
        self.assertContains(response, "Not in the research")

    def test_save_brief(self):
        self.client.force_login(self.writer)
        brief_url = reverse("newsdesk_articles:brief", args=[self.ws.pk])
        data = {"article_type": "explainer", "brief": "New brief", "tone": "brisk"}
        self.assertRedirects(self.client.post(brief_url, data), self.url + "?tab=brief")
        self.ws.refresh_from_db()
        self.assertEqual((self.ws.brief, self.ws.tone, self.ws.article_type), ("New brief", "brisk", "explainer"))

        response = self.client.post(brief_url, {"article_type": "explainer", "brief": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")

    def test_readers_of_the_admin_without_edit_rights_cannot_change_the_brief(self):
        viewer = User.objects.create_user("viewer", "v@example.com", "pass")
        viewer.user_permissions.add(*self.writer.groups.first().permissions.filter(codename="access_admin"))
        self.client.force_login(viewer)
        response = self.client.post(reverse("newsdesk_articles:brief", args=[self.ws.pk]), {"brief": "x"})
        self.assertRedirects(response, reverse("wagtailadmin_home"), fetch_redirect_response=False)
        self.ws.refresh_from_db()
        self.assertNotEqual(self.ws.brief, "x")


class VersionTests(WorkspaceTestCase):
    def setUp(self):
        self.ws = self.make_workspace()
        self.first = self.make_version(self.ws, body=[paragraph("Prices rose 30% in a month."), heading("Why")])
        body = [dict(b) for b in self.first.body]
        body[0] = paragraph("Prices rose 35% in a month.", block_id=body[0]["id"])
        body.append(paragraph("A new closing paragraph."))
        self.second = self.make_version(self.ws, body=body, change_summary="Updated the figure.")
        self.url = reverse("newsdesk_articles:detail", args=[self.ws.pk])

    def test_diff_matches_blocks_by_id(self):
        diff = diff_versions(self.first, self.second)
        self.assertEqual([row["status"] for row in diff["blocks"]], ["changed", "same", "added"])
        self.assertIn("<del>30%</del><ins>35%</ins>", str(diff["blocks"][0]["html"]))
        self.assertEqual(diff["changed_blocks"], 2)
        removed = diff_versions(self.second, self.first)
        self.assertEqual(removed["blocks"][-1]["status"], "removed")

    def test_word_diff_escapes_text(self):
        self.assertEqual(str(word_diff("<b>a</b>", "<b>a</b>")), "&lt;b&gt;a&lt;/b&gt;")

    def test_changes_view_and_old_version_view(self):
        self.client.force_login(self.writer)
        response = self.client.get(self.url + "?compare=2")
        self.assertContains(response, "Changes in version 2 compared with version 1")
        self.assertContains(response, "Updated the figure.")
        response = self.client.get(self.url + "?v=1")
        self.assertContains(response, "You are looking at version 1")
        self.assertContains(response, "30% in a month")

    def test_restore_creates_a_new_version_with_the_same_blocks(self):
        flag = FactCheckFlag.objects.create(
            workspace=self.ws, version=self.first, claim="30%", severity="medium", issue="Check the period"
        )
        self.client.force_login(self.writer)
        response = self.client.post(reverse("newsdesk_articles:restore", args=[self.ws.pk, 1]))
        self.assertRedirects(response, self.url + "?tab=versions")
        self.ws.refresh_from_db()
        restored = self.ws.current_version
        self.assertEqual((restored.number, restored.body, restored.origin), (3, self.first.body, "human"))
        self.assertEqual(restored.based_on, self.first)
        self.assertEqual(restored.flags.get().claim, flag.claim)
        self.assertEqual(self.ws.versions.count(), 3)

    def test_no_restore_while_agents_are_working(self):
        AgentRun.objects.create(workspace=self.ws, status=AgentRun.Status.RUNNING)
        self.client.force_login(self.editor)
        self.client.post(reverse("newsdesk_articles:restore", args=[self.ws.pk, 1]))
        self.assertEqual(self.ws.versions.count(), 2)

    def test_restore_function_keeps_history(self):
        restore_version(self.ws, self.first, self.editor)
        self.assertEqual(list(self.ws.versions.values_list("number", flat=True)), [3, 2, 1])


class CitationTests(WorkspaceTestCase):
    def test_citations_link_known_sources_only(self):
        html = str(cite("A [S1] B [S2]", known={1}))
        self.assertIn('href="#source-1"', html)
        self.assertIn("S2?", html)

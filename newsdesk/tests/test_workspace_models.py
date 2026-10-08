from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from core.newsroom import bootstrap
from newsdesk.content import block_text, ensure_ids, html_to_text, word_count
from newsdesk.models import (
    AgentDefinition,
    AgentRun,
    ArticleSession,
    FactCheckFlag,
    InlineComment,
    ModelPrice,
    NewsroomAISettings,
    Source,
    Topic,
)
from newsdesk.roles import DEFAULT_HOUSE_STYLE, STARTER_AGENTS, WRITER_PROMPT

from .base import WorkspaceTestCase, heading, paragraph


class AgentSetupTests(WorkspaceTestCase):
    def test_bootstrap_creates_every_agent_on_the_default_model(self):
        roles = {row[0] for row in STARTER_AGENTS}
        self.assertEqual(set(AgentDefinition.objects.values_list("role", flat=True)), roles)
        self.assertEqual(set(AgentDefinition.objects.values_list("model", flat=True)), {"claude-opus-5-5"})
        researcher = AgentDefinition.for_role("researcher")
        self.assertTrue(researcher.web_search and researcher.web_fetch)
        self.assertFalse(AgentDefinition.for_role("writer").web_search)

    def test_bootstrap_refreshes_starter_prompts_but_keeps_editors_changes(self):
        writer = AgentDefinition.for_role("writer")
        writer.system_prompt = "Old starter prompt"
        writer.save()
        editor = AgentDefinition.for_role("editor")
        editor.system_prompt = "Our own editing rules"
        editor.customised = True
        editor.save()
        bootstrap()
        writer.refresh_from_db()
        editor.refresh_from_db()
        self.assertEqual(writer.system_prompt, WRITER_PROMPT)
        self.assertEqual(editor.system_prompt, "Our own editing rules")
        self.assertEqual(AgentDefinition.objects.count(), len(STARTER_AGENTS))

    def test_required_agents_cannot_be_switched_off(self):
        writer = AgentDefinition.for_role("writer")
        writer.active = False
        with self.assertRaises(ValidationError):
            writer.full_clean()
        seo = AgentDefinition.for_role("seo")
        seo.active = False
        seo.full_clean()

    def test_model_prices_estimate_cost(self):
        price = ModelPrice.objects.get(model="claude-opus-5-5")
        cost = price.cost(input_tokens=1_000_000, output_tokens=100_000, cache_read_tokens=1_000_000)
        self.assertEqual(cost, Decimal("4") + Decimal("2") + Decimal("0.20"))

    def test_settings_default_to_the_house_style(self):
        settings = NewsroomAISettings.load()
        self.assertEqual(settings.house_style, DEFAULT_HOUSE_STYLE)
        self.assertEqual(settings.web_search_cost_per_1000, Decimal("10.00"))

    def test_bootstrap_upgrades_an_untouched_house_style_only(self):
        from newsdesk.roles import PREVIOUS_HOUSE_STYLES

        settings = NewsroomAISettings.load()
        settings.house_style = PREVIOUS_HOUSE_STYLES[0]
        settings.save()
        bootstrap()
        self.assertEqual(NewsroomAISettings.load().house_style, DEFAULT_HOUSE_STYLE)
        self.assertIn('never write as "I"', DEFAULT_HOUSE_STYLE)

        settings = NewsroomAISettings.load()
        settings.house_style = "Our own style."
        settings.save()
        bootstrap()
        self.assertEqual(NewsroomAISettings.load().house_style, "Our own style.")

    def test_desks_never_auto_publish_by_default(self):
        self.assertFalse(self.economy.auto_publish)


class PermissionTests(WorkspaceTestCase):
    def test_writers_brief_and_give_feedback_editors_approve(self):
        self.assertTrue(self.writer.has_perm("newsdesk.add_articleworkspace"))
        self.assertTrue(self.writer.has_perm("newsdesk.add_topic"))
        self.assertFalse(self.writer.has_perm("newsdesk.approve_articleworkspace"))
        self.assertFalse(self.writer.has_perm("newsdesk.change_agentdefinition"))
        self.assertTrue(self.editor.has_perm("newsdesk.approve_articleworkspace"))
        self.assertTrue(self.editor.has_perm("newsdesk.change_agentdefinition"))
        self.assertTrue(self.editor.has_perm("newsdesk.change_newsroomaisettings"))


class TopicTests(WorkspaceTestCase):
    def test_topic_moves_through_its_lifecycle(self):
        topic = self.make_topic(status=Topic.Status.SUGGESTED)
        topic.article_started()
        self.assertEqual(topic.status, Topic.Status.IN_PROGRESS)
        topic.article_published()
        topic.article_started()  # a second article doesn't un-publish the topic
        self.assertEqual(topic.status, Topic.Status.PUBLISHED)

    def test_a_topic_can_have_several_articles(self):
        topic = self.make_topic()
        self.make_workspace(topic)
        self.make_workspace(topic, brief="A second angle")
        self.assertEqual(topic.articles.count(), 2)


class WorkspaceTests(WorkspaceTestCase):
    def test_new_workspace_gets_its_own_session(self):
        a, b = self.make_workspace(), self.make_workspace()
        self.assertEqual(ArticleSession.objects.count(), 2)
        self.assertNotEqual(a.session.pk, b.session.pk)
        self.assertEqual(a.title, "Why onion prices keep spiking")

    def test_versions_are_numbered_per_workspace(self):
        a, b = self.make_workspace(), self.make_workspace()
        self.make_version(a)
        v2 = self.make_version(a, headline="Revised")
        self.assertEqual(v2.number, 2)
        self.assertEqual(self.make_version(b).number, 1)
        self.assertEqual(a.title, "Revised")

    def test_status_follows_the_article(self):
        ws = self.make_workspace()
        self.assertEqual(ws.refresh_status(), ws.Status.BRIEF)

        run = AgentRun.objects.create(workspace=ws)
        self.assertEqual(ws.refresh_status(), ws.Status.WORKING)
        run.status = AgentRun.Status.SUCCEEDED
        run.save()

        version = self.make_version(ws)
        self.assertEqual(ws.refresh_status(), ws.Status.READY)

        flag = FactCheckFlag.objects.create(
            workspace=ws, version=version, claim="30%", severity="high", issue="Not in the research"
        )
        self.assertEqual(ws.refresh_status(), ws.Status.ATTENTION)
        flag.status = FactCheckFlag.Status.DISMISSED
        flag.save()
        self.assertEqual(ws.refresh_status(), ws.Status.READY)

        ws.approved_version = version
        ws.save()
        self.assertEqual(ws.refresh_status(), ws.Status.APPROVED)
        self.make_version(ws, headline="Changed after approval")
        self.assertEqual(ws.refresh_status(), ws.Status.READY)

    def test_failed_last_run_needs_attention(self):
        ws = self.make_workspace()
        self.make_version(ws)
        AgentRun.objects.create(workspace=ws, status=AgentRun.Status.FAILED, error="Rate limited")
        self.assertEqual(ws.refresh_status(), ws.Status.ATTENTION)

    def test_only_one_active_run_per_article(self):
        ws, other = self.make_workspace(), self.make_workspace()
        AgentRun.objects.create(workspace=ws)
        AgentRun.objects.create(workspace=other)  # other articles are independent
        AgentRun.objects.create(workspace=ws, status=AgentRun.Status.FAILED)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AgentRun.objects.create(workspace=ws, status=AgentRun.Status.RUNNING)

    def test_inline_comment_starts_anchored_to_its_version(self):
        ws = self.make_workspace()
        version = self.make_version(ws)
        block_id = version.body[0]["id"]
        comment = InlineComment.objects.create(
            workspace=ws, version=version, block_id=block_id, start=0, end=6, quote="Prices", comment="Which prices?"
        )
        self.assertEqual(comment.anchored_version, version)
        self.assertEqual(version.block_text(block_id)[comment.start : comment.end], "Prices")


class SourceTests(WorkspaceTestCase):
    def test_sources_are_numbered_per_article_and_deduplicated_by_url(self):
        a, b = self.make_workspace(), self.make_workspace()
        s1 = Source.record(a, url="https://agmarknet.gov.in/", title="Agmarknet", excerpt="Daily prices")
        s2 = Source.record(a, url="https://pib.gov.in/x", title="PIB")
        again = Source.record(a, url="https://agmarknet.gov.in/", excerpt="Arrivals data")
        editor_note = Source.record(a, title="Notes from the editor", origin=Source.Origin.EDITOR)
        self.assertEqual((s1.number, s2.number, editor_note.number), (1, 2, 3))
        self.assertEqual(again.pk, s1.pk)
        self.assertIn("Arrivals data", again.excerpt)
        self.assertEqual(Source.record(b, url="https://agmarknet.gov.in/").number, 1)

    def test_version_lists_cited_sources_in_order(self):
        ws = self.make_workspace()
        first = Source.record(ws, url="https://a.example/", title="A")
        second = Source.record(ws, url="https://b.example/", title="B")
        version = self.make_version(ws, source_numbers=[second.number, first.number])
        self.assertEqual(version.sources(), [second, first])


class ContentTests(WorkspaceTestCase):
    def test_block_text_for_every_agent_block(self):
        self.assertEqual(html_to_text("<p>One &amp; two</p><p>Three</p>"), "One & two\n\nThree")
        self.assertEqual(block_text(heading("What next")), "What next")
        self.assertEqual(
            block_text({"type": "stat", "value": {"figure": "6.5%", "label": "GDP growth", "source": "NSO"}}),
            "6.5% — GDP growth (source: NSO)",
        )
        self.assertEqual(
            block_text({"type": "key_points", "value": {"title": "Key points", "points": ["a", "b"]}}),
            "Key points\n• a\n• b",
        )
        self.assertEqual(block_text({"type": "image", "value": 3}), "")

    def test_ids_and_word_count(self):
        body = ensure_ids([{"type": "paragraph", "value": "<p>Four words right here</p>"}, heading("Two words")])
        self.assertTrue(all(b["id"] for b in body))
        self.assertEqual(word_count(body), 6)
        self.assertEqual(paragraph("x")["type"], "paragraph")

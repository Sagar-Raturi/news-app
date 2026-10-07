import os
from types import SimpleNamespace
from unittest import mock

import anthropic
import httpx2
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from wagtail.models import WorkflowState

from core.newsroom import bootstrap
from news.models import ArticlePage, Author
from newsdesk.desks import STARTER_DESKS
from newsdesk.models import ArticleNote, DeskAgent, DeskFeedback, DraftRequest
from newsdesk.prompts import HOUSE_RULES, build_system, build_user_message
from newsdesk.publishing import body_blocks, create_article, safe_sources
from newsdesk.schema import ArticleDraft, DraftBlock, DraftSource
from newsdesk.tasks import draft_article
from newsdesk.writer import AnthropicWriter, DraftError, DraftResult, FakeWriter

User = get_user_model()
MATERIAL = "Ministry note on onion export curbs. Data: https://agmarknet.gov.in/ Prices up 30% in a month."


def block(type, text="", detail="", points=None, source=""):
    return DraftBlock(type=type, text=text, detail=detail, points=points or [], source=source)


def make_draft(**overrides):
    data = dict(
        headline="Onion prices climb as exports are curbed",
        standfirst="Why the kitchen staple keeps spiking.",
        body=[block("paragraph", "Prices rose sharply this month.")],
        sources=[DraftSource(title="Agmarknet", publisher="Government of India", url="https://agmarknet.gov.in/")],
        tags=["Inflation", "Agriculture"],
        editor_notes="Check the 30% figure against the latest bulletin.",
    )
    data.update(overrides)
    return ArticleDraft(**data)


class NewsdeskTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        site = bootstrap()
        cls.site = site
        cls.economy = DeskAgent.objects.get(slug="economy")
        cls.politics = DeskAgent.objects.get(slug="politics")
        cls.writer = User.objects.create_user("writer", "w@example.com", "pass")
        cls.writer.groups.add(site["writers"])
        cls.editor = User.objects.create_user("editor", "e@example.com", "pass")
        cls.editor.groups.add(site["editors"])
        cls.meera = Author.objects.create(name="Meera Deshpande", slug="meera-deshpande", user=cls.writer)
        cls.desk_author = Author.objects.create(name="Economy Desk", slug="economy-desk")

    def make_request(self, **kwargs):
        kwargs.setdefault("desk", self.economy)
        kwargs.setdefault("article_type", "news")
        kwargs.setdefault("brief", "Onion prices are climbing. Explain why.")
        kwargs.setdefault("source_material", MATERIAL)
        kwargs.setdefault("requested_by", self.writer)
        return DraftRequest.objects.create(**kwargs)


class DeskSetupTests(NewsdeskTestCase):
    def test_bootstrap_creates_one_desk_per_news_section(self):
        self.assertEqual(DeskAgent.objects.count(), len(STARTER_DESKS))
        self.assertFalse(DeskAgent.objects.filter(section__slug="opinion").exists())
        self.assertEqual(self.economy.section.slug, "economy")

    def test_bootstrap_keeps_editors_changes(self):
        self.economy.style_guide = "Our own rules."
        self.economy.save()
        bootstrap()
        self.economy.refresh_from_db()
        self.assertEqual(self.economy.style_guide, "Our own rules.")
        self.assertEqual(DeskAgent.objects.count(), len(STARTER_DESKS))

    def test_ai_never_writes_opinion(self):
        for article_type in ("opinion", "editorial"):
            request = DraftRequest(desk=self.economy, article_type=article_type, brief="x", source_material="y")
            with self.assertRaises(ValidationError):
                request.clean()

    def test_inactive_desk_rejected(self):
        self.economy.active = False
        self.economy.save()
        with self.assertRaises(ValidationError):
            DraftRequest(desk=self.economy, article_type="news", brief="x", source_material="y").clean()


class MemoryAndPromptTests(NewsdeskTestCase):
    def test_memory_is_per_desk_and_per_type(self):
        general = DeskFeedback.objects.create(desk=self.economy, note="Lead with households.")
        explainer = DeskFeedback.objects.create(desk=self.economy, article_type="explainer", note="Use a worked example.")
        DeskFeedback.objects.create(desk=self.economy, article_type="analysis", note="Analysis only.")
        DeskFeedback.objects.create(desk=self.economy, note="Forgotten.", active=False)
        DeskFeedback.objects.create(desk=self.politics, note="Politics only.")

        self.assertEqual(self.economy.memory("explainer"), [general, explainer])
        self.assertEqual(self.economy.memory("news"), [general])
        self.assertEqual(self.economy.memory_size(), 3)

    def test_system_prompt_has_cached_house_rules_and_desk_memory(self):
        DeskFeedback.objects.create(desk=self.economy, article_type="explainer", note="Use a worked example.")
        system = build_system(self.economy, "explainer")
        self.assertEqual(len(system), 2)
        self.assertTrue(all(b["cache_control"] == {"type": "ephemeral"} for b in system))
        self.assertEqual(system[0]["text"], HOUSE_RULES)
        self.assertIn("Use only facts", HOUSE_RULES)
        self.assertIn("Economy desk", system[1]["text"])
        self.assertIn(self.economy.style_guide, system[1]["text"])
        self.assertIn("[Explainer] Use a worked example.", system[1]["text"])
        self.assertNotIn("worked example", build_system(self.economy, "news")[1]["text"])

    def test_special_instructions_reach_the_first_draft_only_for_that_article(self):
        message = build_user_message(self.make_request(article_instructions="Keep it under 600 words."))
        self.assertIn("<article_instructions>\nKeep it under 600 words.\n</article_instructions>", message)
        self.assertNotIn("Keep it under 600 words", build_system(self.economy, "news")[1]["text"])
        self.assertNotIn("<article_instructions>", build_user_message(self.make_request()))

    def test_user_message_carries_brief_and_material(self):
        message = build_user_message(self.make_request(article_type="explainer"))
        self.assertTrue(message.startswith("Write an explainer."))
        self.assertIn("<brief>\nOnion prices are climbing. Explain why.\n</brief>", message)
        self.assertIn(MATERIAL, message)
        self.assertIn("qa blocks", message)


def fake_response(draft=None, stop_reason="end_turn"):
    return SimpleNamespace(
        parsed_output=draft,
        stop_reason=stop_reason,
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=1200, output_tokens=900, cache_read_input_tokens=800),
    )


class AnthropicWriterTests(NewsdeskTestCase):
    def writer_with(self, response=None, error=None):
        client = mock.MagicMock()
        if error:
            client.beta.messages.parse.side_effect = error
        else:
            client.beta.messages.parse.return_value = response
        return AnthropicWriter(client=client), client

    def test_calls_claude_with_desk_settings_and_structured_output(self):
        self.economy.effort = "xhigh"
        self.economy.save()
        draft = make_draft()
        writer, client = self.writer_with(fake_response(draft))
        result = writer.write(self.make_request())

        kwargs = client.beta.messages.parse.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-opus-5-5")
        self.assertEqual(kwargs["output_format"], ArticleDraft)
        self.assertEqual(kwargs["output_config"], {"effort": "xhigh"})
        self.assertEqual(kwargs["fallbacks"], "default")
        self.assertEqual(kwargs["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(kwargs["system"], build_system(self.economy, "news"))
        self.assertIn(MATERIAL, kwargs["messages"][0]["content"])
        self.assertIs(result.draft, draft)
        self.assertEqual((result.input_tokens, result.output_tokens, result.cache_read_tokens), (1200, 900, 800))

    def test_refusal_and_truncation_and_empty_output_fail_cleanly(self):
        for response, message in [
            (fake_response(stop_reason="refusal"), "declined"),
            (fake_response(stop_reason="max_tokens"), "length limit"),
            (fake_response(draft=None), "usable draft"),
        ]:
            writer, _ = self.writer_with(response)
            with self.assertRaisesMessage(DraftError, message):
                writer.write(self.make_request())

    def test_api_errors_become_draft_errors(self):
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        writer, _ = self.writer_with(error=anthropic.APIConnectionError(request=request))
        with self.assertRaisesMessage(DraftError, "network"):
            writer.write(self.make_request())

    def test_missing_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesMessage(DraftError, "ANTHROPIC_API_KEY"):
                AnthropicWriter().write(self.make_request())


class PublishingTests(NewsdeskTestCase):
    def test_blocks_are_escaped_and_mapped(self):
        draft = make_draft(
            body=[
                block("paragraph", "First <script>alert(1)</script> para.\n\nSecond para."),
                block("heading", "What next"),
                block("pullquote", "Prices will ease.", "A trader in Lasalgaon"),
                block("key_points", "Key points", points=["One", " ", "Two"]),
                block("qa", "Why now?", "Because rain."),
                block("stat", "30%", "Rise in a month", source="Agmarknet"),
                block("callout", "What happens next", "Watch arrivals."),
                block("qa", "Unanswered?", ""),
                block("paragraph", "   "),
            ]
        )
        blocks = body_blocks(draft)
        self.assertEqual([b["type"] for b in blocks], ["paragraph", "heading", "pullquote", "key_points", "qa", "stat", "callout"])
        self.assertEqual(blocks[0]["value"], "<p>First &lt;script&gt;alert(1)&lt;/script&gt; para.</p><p>Second para.</p>")
        self.assertEqual(blocks[3]["value"]["points"], ["One", "Two"])
        self.assertEqual(blocks[4]["value"]["answer"], "<p>Because rain.</p>")

    def test_only_urls_from_the_material_survive(self):
        draft = make_draft(
            sources=[
                DraftSource(title="Agmarknet", publisher="GoI", url="https://agmarknet.gov.in/"),
                DraftSource(title="Invented", publisher="X", url="https://example.com/made-up"),
                DraftSource(title="Script", publisher="X", url="javascript:alert(1)"),
            ]
        )
        urls = [s["value"]["url"] for s in safe_sources(draft, MATERIAL)]
        self.assertEqual(urls, ["https://agmarknet.gov.in/", "", ""])

    def test_creates_ai_assisted_draft_in_review(self):
        request = self.make_request()
        article = create_article(request, DraftResult(draft=make_draft(), model="claude-opus-5-5"))
        article.refresh_from_db()
        self.assertFalse(article.live)
        self.assertEqual(article.get_parent().slug, "economy")
        self.assertTrue(article.ai_assisted)
        self.assertIn("Economy desk AI agent", article.ai_note)
        self.assertEqual(article.authors, [self.meera])
        self.assertEqual(article.owner, self.writer)
        self.assertEqual(sorted(article.tags.names()), ["Agriculture", "Inflation"])
        self.assertEqual(article.current_workflow_state.status, WorkflowState.STATUS_IN_PROGRESS)
        self.assertEqual(self.client.get(article.url or "/economy/x/").status_code, 404)

    def test_byline_fallbacks_and_unique_slugs(self):
        self.economy.default_author = self.desk_author
        self.economy.save()
        no_profile = User.objects.create_user("intern", "i@example.com", "pass")
        first = create_article(self.make_request(requested_by=no_profile), DraftResult(make_draft(), "m"))
        second = create_article(self.make_request(byline=self.desk_author), DraftResult(make_draft(), "m"))
        self.assertEqual(first.authors, [self.desk_author])
        self.assertEqual(second.authors, [self.desk_author])
        self.assertNotEqual(first.slug, second.slug)


@override_settings(NEWSDESK_WRITER="fake")
class TaskTests(NewsdeskTestCase):
    def test_commission_enqueues_after_commit(self):
        with mock.patch("newsdesk.tasks.draft_article.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                request = self.make_request()
        delay.assert_called_once_with(request.pk)

    def test_task_writes_draft_and_records_result(self):
        request = self.make_request()
        self.assertEqual(draft_article(request.pk), DraftRequest.Status.DONE)
        request.refresh_from_db()
        self.assertEqual(request.status, DraftRequest.Status.DONE)
        self.assertEqual(request.model_used, "fake")
        self.assertTrue(request.editor_notes)
        self.assertTrue(request.article.ai_assisted)
        self.assertEqual(request.article.specific.current_workflow_state.status, WorkflowState.STATUS_IN_PROGRESS)
        # Running again does not create a second article.
        draft_article(request.pk)
        self.assertEqual(ArticlePage.objects.count(), 1)

    def test_special_instructions_become_the_articles_first_note(self):
        request = self.make_request(article_instructions="  Keep it under 600 words.  ")
        draft_article(request.pk)
        request.refresh_from_db()
        note = ArticleNote.objects.get()
        self.assertEqual((note.article_id, note.note, note.source), (request.article_id, "Keep it under 600 words.", ArticleNote.Source.COMMISSION))
        self.assertEqual(note.created_by, self.writer)
        points = [b.value["points"] for b in request.article.specific.body if b.block_type == "key_points"][0]
        self.assertIn("Special instructions: Keep it under 600 words.", points)

    def test_failure_is_recorded_for_editors(self):
        request = self.make_request()
        with mock.patch.object(FakeWriter, "write", side_effect=DraftError("The model declined.")):
            self.assertEqual(draft_article(request.pk), DraftRequest.Status.FAILED)
        request.refresh_from_db()
        self.assertEqual(request.error, "The model declined.")
        self.assertIsNone(request.article)
        self.assertFalse(ArticlePage.objects.exists())


@override_settings(NEWSDESK_WRITER="fake")
class ReviewFeedbackTests(NewsdeskTestCase):
    def reject(self, article, comment):
        state = article.current_workflow_state
        task_state = state.current_task_state
        task_state.task.specific.on_action(task_state, self.editor, "reject", comment=comment)

    def test_request_changes_comment_stays_with_the_article(self):
        request = self.make_request(article_type="explainer")
        draft_article(request.pk)
        request.refresh_from_db()
        self.reject(request.article.specific, "Explain who pays the levy before the numbers.")

        note = ArticleNote.objects.get()
        self.assertEqual(note.article_id, request.article_id)
        self.assertEqual(note.source, ArticleNote.Source.REVIEW)
        self.assertEqual(note.created_by, self.editor)
        # Not desk memory: other Economy drafts never see it.
        self.assertFalse(DeskFeedback.objects.exists())
        self.assertNotIn("Explain who pays the levy", build_system(self.economy, "explainer")[1]["text"])

    def test_promoted_note_becomes_a_desk_rule_once(self):
        request = self.make_request(article_type="explainer")
        draft_article(request.pk)
        request.refresh_from_db()
        self.reject(request.article.specific, "Explain who pays the levy before the numbers.")
        note = ArticleNote.objects.get()

        rule = note.promote(self.economy, "explainer", self.editor)
        self.assertEqual(note.promote(self.economy, "explainer", self.editor), rule)
        self.assertEqual(DeskFeedback.objects.count(), 1)
        self.assertEqual((rule.desk, rule.article_type, rule.source), (self.economy, "explainer", DeskFeedback.Source.REVIEW))
        self.assertEqual((rule.article_id, rule.created_by), (request.article_id, self.editor))
        self.assertIn("[Explainer] Explain who pays the levy", build_system(self.economy, "explainer")[1]["text"])
        self.assertNotIn("Explain who pays the levy", build_system(self.politics, "explainer")[1]["text"])

    def test_empty_comment_or_human_article_adds_nothing(self):
        request = self.make_request()
        draft_article(request.pk)
        request.refresh_from_db()
        self.reject(request.article.specific, "")
        human = ArticlePage(title="Human story", standfirst="s", body=[], live=False, owner=self.writer)
        self.economy.section.add_child(instance=human)
        human.save_revision(user=self.writer)
        self.site["workflow"].start(human, self.writer)
        self.reject(human, "Tighten the intro.")
        self.assertFalse(ArticleNote.objects.exists())
        self.assertFalse(DeskFeedback.objects.exists())


@override_settings(NEWSDESK_WRITER="fake")
class ArticleNoteTests(NewsdeskTestCase):
    def setUp(self):
        self.request = self.make_request()
        draft_article(self.request.pk)
        self.request.refresh_from_db()
        self.article = self.request.article.specific

    def test_remember_skips_blank_and_duplicate_notes(self):
        first = ArticleNote.remember(self.article, "Name the regulator.", ArticleNote.Source.REVIEW, self.editor)
        self.assertEqual(ArticleNote.remember(self.article, " Name  the regulator. ", ArticleNote.Source.REVISION), first)
        self.assertIsNone(ArticleNote.remember(self.article, "   ", ArticleNote.Source.MANUAL))
        self.assertEqual(ArticleNote.objects.count(), 1)
        first.active = False
        first.save()
        # A forgotten note can be given again.
        self.assertNotEqual(ArticleNote.remember(self.article, "Name the regulator.", ArticleNote.Source.MANUAL), first)

    def test_standing_notes_are_active_own_article_and_skip_current(self):
        other = create_article(self.make_request(), DraftResult(make_draft(), "m"))
        a = ArticleNote.remember(self.article, "Lead with households.", ArticleNote.Source.REVIEW)
        ArticleNote.objects.create(article=self.article, note="Forgotten.", active=False)
        b = ArticleNote.remember(self.article, "Shorter, please.", ArticleNote.Source.REVISION)
        ArticleNote.remember(other, "Other article.", ArticleNote.Source.REVIEW)
        self.assertEqual(ArticleNote.standing(self.article), [a, b])
        self.assertEqual(ArticleNote.standing(self.article, exclude="Shorter,  please."), [a])

    def test_standing_notes_skip_text_already_covered(self):
        review = ArticleNote.remember(self.article, "Explain the wedding angle.", ArticleNote.Source.REVIEW)
        extended = ArticleNote.remember(
            self.article, "Explain the wedding angle. Also add the RBI figure.", ArticleNote.Source.REVISION
        )
        self.assertNotEqual(review, extended)
        self.assertEqual(ArticleNote.standing(self.article), [extended])
        self.assertEqual(ArticleNote.standing(self.article, exclude="explain the wedding angle. also add the RBI figure. And shorten it."), [])

    def test_notes_go_when_the_article_is_deleted(self):
        ArticleNote.remember(self.article, "Lead with households.", ArticleNote.Source.REVIEW)
        self.article.delete()
        self.assertFalse(ArticleNote.objects.exists())


class AdminTests(NewsdeskTestCase):
    add_url = reverse("wagtailsnippets_newsdesk_draftrequest:add")

    def test_writer_commissions_a_draft(self):
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(self.add_url).status_code, 200)
        with mock.patch("newsdesk.tasks.draft_article.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    self.add_url,
                    {
                        "desk": self.economy.pk,
                        "article_type": "explainer",
                        "brief": "Explain GST changes.",
                        "article_instructions": "No named companies.",
                        "source_material": MATERIAL,
                        "byline": "",
                    },
                )
        self.assertEqual(response.status_code, 302)
        request = DraftRequest.objects.get()
        self.assertEqual((request.requested_by, request.article_instructions), (self.writer, "No named companies."))
        delay.assert_called_once_with(request.pk)
        inspect = self.client.get(reverse("wagtailsnippets_newsdesk_draftrequest:inspect", args=[request.pk]))
        self.assertContains(inspect, "Explain GST changes.")
        self.assertContains(inspect, "No named companies.")

    def test_opinion_cannot_be_commissioned(self):
        self.client.force_login(self.writer)
        response = self.client.post(
            self.add_url,
            {"desk": self.economy.pk, "article_type": "opinion", "brief": "b", "source_material": "m", "byline": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DraftRequest.objects.exists())

    def test_only_editors_change_desks(self):
        edit_url = reverse("wagtailsnippets_newsdesk_deskagent:edit", args=[self.economy.pk])
        self.client.force_login(self.writer)
        self.assertNotEqual(self.client.get(edit_url).status_code, 200)
        self.client.force_login(self.editor)
        response = self.client.get(edit_url)
        self.assertContains(response, "Memory: feedback for this desk")
        self.assertEqual(self.client.get(reverse("wagtailsnippets_newsdesk_deskagent:list")).status_code, 200)

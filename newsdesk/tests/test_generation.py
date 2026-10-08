from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from news.models import ArticlePage
from newsdesk.jobs import ArticleBusy, cancel_run, retry_run, start_run
from newsdesk.models import (
    AgentRun,
    AgentStep,
    ArticleVersion,
    ArticleWorkspace,
    DeskFeedback,
    FactCheckFlag,
    SessionMessage,
    Source,
    Topic,
)
from newsdesk import approval
from newsdesk.pagesync import import_page_edits
from newsdesk.pipeline.fake import ScriptedCaller
from newsdesk.pipeline.llm import AgentError, TransientAgentError
from newsdesk.pipeline.runner import Pipeline
from newsdesk.pipeline.schemas import FullDraft
from newsdesk.roles import DEFAULT_HOUSE_STYLE
from newsdesk.schema import DraftBlock
from newsdesk.tasks import run_agents

from .base import WorkspaceTestCase, clean_check, writer_only

MATERIAL = "https://agmarknet.gov.in/ Agmarknet daily prices\nPrices up 30% in a month, says a trader body."


def block(type, text="", detail="", points=None):
    return DraftBlock(type=type, text=text, detail=detail, points=points or [], source="")


def full_draft(**overrides):
    data = dict(
        headline="Onion prices keep spiking",
        standfirst="Storage, not export bans, is the missing piece.",
        body=[
            block("paragraph", "Prices rose 30% in a month [S1], traders say [S2]. Invented [S9]."),
            block("heading", "Why it keeps happening"),
            block("key_points", "Key points", points=["No buffer stock [S1]", "Exports curbed"]),
        ],
        tags=["Inflation", "Agriculture"],
        notes="Could not find official arrivals data.",
    )
    data.update(overrides)
    return FullDraft(**data)


class GenerationTestCase(WorkspaceTestCase):
    def setUp(self):
        self.ws = self.make_workspace(sources_to_use=MATERIAL, target_words=700)

    def run_pipeline(self, *responses, kind=AgentRun.Kind.GENERATE, usage=None):
        caller = ScriptedCaller(writer_only(*responses), usage=usage)
        with mock.patch("newsdesk.jobs._enqueue"):
            run = start_run(self.ws, kind, self.editor)
        Pipeline(run, caller=caller).execute()
        run.refresh_from_db()
        self.ws.refresh_from_db()
        return run, caller


class StartRunTests(GenerationTestCase):
    def test_run_is_queued_after_commit_and_one_at_a_time(self):
        with mock.patch("newsdesk.tasks.run_agents.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                run = start_run(self.ws, AgentRun.Kind.GENERATE, self.editor)
        delay.assert_called_once_with(run.pk)
        self.assertEqual(self.ws.status, ArticleWorkspace.Status.WORKING)
        with self.assertRaises(ArticleBusy):
            start_run(self.ws, AgentRun.Kind.GENERATE, self.editor)
        other = self.make_workspace(self.make_topic("Another"))
        with mock.patch("newsdesk.jobs._enqueue"):
            start_run(other, AgentRun.Kind.GENERATE, self.editor)  # other articles aren't blocked


class FirstDraftTests(GenerationTestCase):
    def test_writer_draft_becomes_version_one_and_a_page_draft(self):
        run, caller = self.run_pipeline(full_draft(), usage={"input_tokens": 10_000, "output_tokens": 2_000})
        self.assertEqual(run.status, AgentRun.Status.SUCCEEDED)
        version = self.ws.current_version
        self.assertEqual((version.number, version.origin, version.run), (1, "agent", run))
        self.assertEqual(self.ws.status, ArticleWorkspace.Status.READY)

        # Editor material became numbered sources; the invented [S9] was removed.
        self.assertEqual(self.ws.sources.get(number=1).url, "https://agmarknet.gov.in/")
        self.assertEqual(self.ws.sources.get(number=2).title, "Material supplied by the editor")
        self.assertEqual(version.source_numbers, [1, 2])
        text = version.body[0]["value"]
        self.assertIn("[S1]", text)
        self.assertNotIn("[S9]", text)

        page = self.ws.page
        self.assertFalse(page.live)
        self.assertTrue(page.ai_assisted)
        self.assertEqual(version.page_revision, page.get_latest_revision())
        draft_page = page.get_latest_revision_as_object()
        self.assertEqual(draft_page.title, "Onion prices keep spiking")
        self.assertIn('<a href="https://agmarknet.gov.in/">[1]</a>', draft_page.body.raw_data[0]["value"])
        self.assertEqual(len(draft_page.sources), 2)
        self.assertEqual(page.get_parent().specific, self.economy.section.specific)

        step = run.steps.get(role="writer")
        self.assertEqual((step.status, step.input_tokens), ("succeeded", 10_000))
        self.assertEqual(step.cost, Decimal("0.08"))  # 10k in at $4/M + 2k out at $20/M
        self.assertEqual(run.cost, sum(s.cost for s in run.steps.all()))
        self.assertEqual(list(run.steps.values_list("role", flat=True)), ["orchestrator", "writer", "fact_checker"])

        message = self.ws.session.messages.filter(role=SessionMessage.Role.ORCHESTRATOR).last()
        self.assertIn("Version 1 is ready", message.content)
        self.assertIn("Could not find official arrivals data", message.content)

    def test_writer_gets_brief_sources_house_style_and_section_rules(self):
        DeskFeedback.objects.create(desk=self.economy, note="Always give figures in crore.")
        _run, caller = self.run_pipeline(full_draft())
        request = next(r for r in caller.requests if r.agent.role == "writer")
        system = "\n".join(block["text"] for block in request.system)
        self.assertIn(DEFAULT_HOUSE_STYLE[:80], system)
        self.assertIn(self.economy.style_guide[:40], system)
        self.assertIn("Always give figures in crore.", system)
        message = request.messages[0]["content"]
        self.assertIn(self.ws.brief, message)
        self.assertIn("[S1] Agmarknet daily prices <https://agmarknet.gov.in/>", message)
        self.assertIn("About 700 words.", message)

    def test_regenerate_writes_a_new_version_and_keeps_the_old_one(self):
        self.run_pipeline(full_draft())
        first = self.ws.current_version
        self.run_pipeline(full_draft(headline="A fresh take"))
        second = self.ws.current_version
        self.assertEqual(second.number, 2)
        self.assertEqual(self.ws.versions.count(), 2)
        self.assertFalse({b["id"] for b in first.body} & {b["id"] for b in second.body})
        self.assertEqual(self.ws.page.get_latest_revision_as_object().title, "A fresh take")


class FailureTests(GenerationTestCase):
    def test_failed_step_is_reported_and_can_be_retried(self):
        run, _ = self.run_pipeline(AgentError("The model declined this task."))
        self.assertEqual(run.status, AgentRun.Status.FAILED)
        self.assertEqual(run.steps.get(role="writer").status, AgentStep.Status.FAILED)
        self.assertEqual(self.ws.status, ArticleWorkspace.Status.BRIEF)
        self.assertIn("The run failed", self.ws.session.messages.get(role="system").content)

        with mock.patch("newsdesk.jobs._enqueue"):
            retry_run(run, self.editor)
        run.refresh_from_db()
        self.assertEqual(run.status, AgentRun.Status.QUEUED)
        retry = ScriptedCaller({"writer": [full_draft()], "fact_checker": [clean_check()]})
        Pipeline(run, caller=retry).execute()
        run.refresh_from_db()
        self.assertEqual(run.status, AgentRun.Status.SUCCEEDED)
        self.assertEqual(run.steps.get(role="writer").attempts, 2)
        self.assertNotIn("orchestrator", retry.roles())  # the finished plan step isn't redone

    def test_transient_errors_are_retried_by_the_task(self):
        caller = ScriptedCaller(writer_only(TransientAgentError("Rate limited."), full_draft()))
        with mock.patch("newsdesk.jobs._enqueue"):
            run = start_run(self.ws, AgentRun.Kind.GENERATE, self.editor)
        with mock.patch("newsdesk.pipeline.runner.get_caller", return_value=caller):
            run_agents.apply(args=[run.pk])
        run.refresh_from_db()
        self.assertEqual(run.status, AgentRun.Status.SUCCEEDED)
        self.assertTrue(run.events.filter(message__contains="Retrying in").exists())

    def test_task_gives_up_after_repeated_transient_errors(self):
        caller = ScriptedCaller(writer_only(*[TransientAgentError("Overloaded.")] * 4))
        with mock.patch("newsdesk.jobs._enqueue"):
            run = start_run(self.ws, AgentRun.Kind.GENERATE, self.editor)
        with mock.patch("newsdesk.pipeline.runner.get_caller", return_value=caller):
            run_agents.apply(args=[run.pk])
        run.refresh_from_db()
        self.assertEqual(run.status, AgentRun.Status.FAILED)
        self.assertIn("Gave up after 3 retries", run.error)

    def test_cancelled_run_does_nothing(self):
        with mock.patch("newsdesk.jobs._enqueue"):
            run = start_run(self.ws, AgentRun.Kind.GENERATE, self.editor)
        cancel_run(run, self.editor)
        Pipeline(run, caller=ScriptedCaller()).execute()
        self.ws.refresh_from_db()
        self.assertIsNone(self.ws.current_version)
        self.assertEqual(self.ws.status, ArticleWorkspace.Status.BRIEF)


class HandEditTests(GenerationTestCase):
    def test_page_editor_changes_come_back_as_a_human_version(self):
        self.run_pipeline(full_draft())
        page = self.ws.page.get_latest_revision_as_object()
        self.assertIsNone(import_page_edits(self.ws, self.editor))  # nothing changed yet

        page.save_revision(user=self.editor)  # saved without changes: no new version
        self.assertIsNone(import_page_edits(self.ws, self.editor))

        page.title = "Onion prices: the storage problem"
        body = page.body.raw_data
        body[0]["value"] = body[0]["value"].replace("Prices rose", "Wholesale prices rose")
        page.body = list(body)
        page.save_revision(user=self.editor)
        version = import_page_edits(self.ws, self.editor)
        self.assertEqual((version.number, version.origin, version.created_by), (2, "human", self.editor))
        self.assertEqual(version.headline, "Onion prices: the storage problem")
        self.assertIn("Wholesale prices rose 30% in a month [S1]", version.body[0]["value"])
        self.assertEqual(version.body[0]["id"], self.ws.versions.get(number=1).body[0]["id"])
        self.assertEqual(version.source_numbers, [1, 2])


class ApprovalTests(GenerationTestCase):
    def setUp(self):
        super().setUp()
        self.run_pipeline(full_draft())
        self.version = self.ws.current_version

    def test_serious_flags_block_approval_until_checked(self):
        flag = FactCheckFlag.objects.create(
            workspace=self.ws, version=self.version, claim="30%", severity="high", issue="Unsupported"
        )
        self.ws.refresh_status()
        with self.assertRaises(approval.NotAllowed):
            approval.approve(self.ws, self.editor)
        self.client.force_login(self.editor)
        self.client.post(reverse("newsdesk_articles:accept_flag", args=[self.ws.pk, flag.pk]))
        flag.refresh_from_db()
        self.assertEqual((flag.status, flag.resolved_by), ("dismissed", self.editor))
        approval.approve(self.ws, self.editor)
        self.assertEqual(self.ws.status, ArticleWorkspace.Status.APPROVED)

    def test_publish_only_the_approved_version(self):
        with self.assertRaises(approval.NotAllowed):
            approval.publish(self.ws, self.editor)
        approval.approve(self.ws, self.editor)
        approval.publish(self.ws, self.editor)
        page = ArticlePage.objects.get(pk=self.ws.page_id)
        self.assertTrue(page.live)
        self.assertEqual(page.title, self.version.headline)
        self.assertEqual(self.ws.status, ArticleWorkspace.Status.PUBLISHED)
        self.assertEqual(self.ws.topic.status, Topic.Status.PUBLISHED)

        approval.unpublish(self.ws, self.editor)
        self.assertFalse(ArticlePage.objects.get(pk=self.ws.page_id).live)
        self.assertNotEqual(self.ws.status, ArticleWorkspace.Status.PUBLISHED)

    def test_edits_after_approval_need_approving_again(self):
        approval.approve(self.ws, self.editor)
        page = self.ws.page.get_latest_revision_as_object()
        page.standfirst = "Changed after approval."
        page.save_revision(user=self.writer)
        with self.assertRaises(approval.NotAllowed):
            approval.publish(self.ws, self.editor)
        self.assertFalse(ArticlePage.objects.get(pk=self.ws.page_id).live)
        self.assertEqual(self.ws.current_version.number, 2)

    def test_writers_cannot_approve_or_publish(self):
        self.client.force_login(self.writer)
        self.client.post(reverse("newsdesk_articles:approve", args=[self.ws.pk]))
        self.ws.refresh_from_db()
        self.assertIsNone(self.ws.approved_version)

    def test_nothing_is_published_by_the_agents(self):
        self.assertFalse(ArticlePage.objects.get(pk=self.ws.page_id).live)
        self.assertIsNone(self.ws.published_at)


@override_settings(NEWSDESK_WRITER="fake")
class WorkspaceFlowTests(WorkspaceTestCase):
    """The whole flow through the views, with the offline fake agents."""

    def test_brief_generate_watch_approve_publish(self):
        self.client.force_login(self.editor)
        self.client.post(
            reverse("newsdesk_articles:create"),
            {"new_topic": "Onion prices", "desk": self.economy.pk, "article_type": "analysis", "brief": "Why?"},
        )
        ws = ArticleWorkspace.objects.get()
        detail = reverse("newsdesk_articles:detail", args=[ws.pk])
        self.assertContains(self.client.get(detail), "No draft yet")

        with mock.patch("newsdesk.tasks.run_agents.delay", side_effect=lambda pk: run_agents.apply(args=[pk])):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse("newsdesk_articles:generate", args=[ws.pk]))
        self.assertRedirects(response, detail + "?tab=activity")
        ws.refresh_from_db()
        self.assertEqual(ws.current_version.number, 1)
        self.assertEqual(ws.status, ArticleWorkspace.Status.READY)

        page = self.client.get(detail)
        self.assertContains(page, "(demo draft)")
        self.assertContains(page, "Approve version 1")
        self.assertContains(page, "Writer")

        activity = self.client.get(
            reverse("newsdesk_articles:activity", args=[ws.pk]) + "?watching=1", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(activity["HX-Refresh"], "true")
        self.assertRedirects(
            self.client.get(reverse("newsdesk_articles:activity", args=[ws.pk])), detail + "?tab=activity"
        )

        self.client.post(reverse("newsdesk_articles:approve", args=[ws.pk]))
        self.client.post(reverse("newsdesk_articles:publish", args=[ws.pk]))
        ws.refresh_from_db()
        self.assertEqual(ws.status, ArticleWorkspace.Status.PUBLISHED)
        self.assertContains(self.client.get(detail), "Unpublish")

    def test_generate_while_busy_is_refused(self):
        ws = self.make_workspace()
        AgentRun.objects.create(workspace=ws, status=AgentRun.Status.RUNNING)
        self.client.force_login(self.writer)
        with mock.patch("newsdesk.tasks.run_agents.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(reverse("newsdesk_articles:generate", args=[ws.pk]))
        delay.assert_not_called()
        self.assertEqual(ws.runs.count(), 1)

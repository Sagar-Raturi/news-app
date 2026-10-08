"""The multi-agent pipeline with the LLM mocked: planning, research, fix loop, edits, flags, isolation."""

from types import SimpleNamespace
from unittest import mock

from django.test import override_settings

from newsdesk.jobs import retry_run, start_run
from newsdesk.models import AgentDefinition, AgentRun, ArticleWorkspace, FactCheckFlag, Finding, NewsroomAISettings, SessionMessage, Source
from newsdesk.pipeline import drafts, planning
from newsdesk.pipeline.fake import FakeCaller, ScriptedCaller
from newsdesk.pipeline.llm import AgentError, AgentResponse, Usage
from newsdesk.pipeline.runner import Pipeline
from newsdesk.pipeline.schemas import (
    Analysis,
    BlockEdit,
    Edits,
    FactCheck,
    Flag,
    Outline,
    OutlineSection,
    Perspective,
    PlanStep,
    Seo,
)
from newsdesk.schema import DraftBlock

from .base import WorkspaceTestCase, clean_check, heading, paragraph, plan
from .test_generation import block, full_draft

FULL = ("research", "analyse", "outline", "write", "edit", "seo")


def researcher(*findings, extra_seen=()):
    """A scripted researcher that records findings and 'retrieves' their pages."""

    def run(request):
        for url, text in findings:
            request.tool_handlers["record_finding"](
                {"kind": "fact", "text": text, "detail": "", "url": url, "title": f"Page {url}", "publisher": "Pub"}
            )
        seen = [url for url, _ in findings if "invented" not in url] + list(extra_seen)
        results = [SimpleNamespace(type="web_search_result", url=url) for url in seen]
        return AgentResponse(
            parsed=None, text="Notes: thin on official data.", model="claude-opus-5-5",
            usage=Usage(input_tokens=1000, web_searches=3),
            blocks=[SimpleNamespace(type="web_search_tool_result", content=results)],
        )

    return run


def analysis():
    return Analysis(
        thesis="Storage, not exports, drives the spikes [S1].", context="Context [S1].",
        perspectives=[Perspective(view="Exports matter", evidence="[S2]"), Perspective(view="Storage matters", evidence="[S1]")],
        implications="Cold chains.", uncertainties="Arrivals data is patchy.",
    )


def outline():
    return Outline(
        headline_options=["Onions need cold storage"], standfirst="Why prices spike.",
        sections=[OutlineSection(heading="", points=["Prices [S1]"], words=300)], extras=[],
    )


def edits(*items, headline="", standfirst="", notes="Tightened."):
    return Edits(edits=list(items), headline=headline, standfirst=standfirst, notes=notes)


def flag(claim="Prices rose 30% in a month", severity="high", ref="B1"):
    return Flag(block=ref, claim=claim, severity=severity, issue="Not in the research", suggestion="Cite or cut", sources=[1])


def seo(headline="Onion prices keep spiking. Storage is why"):
    return Seo(headline_options=[headline, "Other"], headline=headline, meta_description="Why onion prices spike.",
               slug="onion-prices-storage", tags=["Inflation", "Agriculture"])


class PipelineTestCase(WorkspaceTestCase):
    def setUp(self):
        self.ws = self.make_workspace()

    def run_with(self, script, kind=AgentRun.Kind.GENERATE, workspace=None, trigger=None):
        workspace = workspace or self.ws
        caller = ScriptedCaller(script)
        with mock.patch("newsdesk.jobs._enqueue"):
            run = start_run(workspace, kind, self.editor, trigger=trigger)
        Pipeline(run, caller=caller).execute()
        run.refresh_from_db()
        workspace.refresh_from_db()
        return run, caller

    def full_script(self, checks=None, **overrides):
        script = {
            "orchestrator": [plan(*FULL, message="Researching first.")],
            "researcher": [researcher(("https://agmarknet.gov.in/", "Prices up 30% in a month"),
                                      ("https://pib.gov.in/x", "Export curbs announced"))],
            "analyst": [analysis()],
            "outliner": [outline()],
            "writer": [full_draft()],
            "editor": [edits()],
            "fact_checker": checks or [clean_check()],
            "seo": [seo()],
        }
        script.update(overrides)
        return script


class FirstDraftPipelineTests(PipelineTestCase):
    def test_every_agent_runs_in_order_and_the_draft_has_sources_and_seo(self):
        run, caller = self.run_with(self.full_script(checks=[FactCheck(summary="One issue.", flags=[flag(severity="medium")])]))
        self.assertEqual(run.status, AgentRun.Status.SUCCEEDED)
        self.assertEqual(
            caller.roles(), ["orchestrator", "researcher", "analyst", "outliner", "writer", "editor", "fact_checker", "seo"]
        )
        version = self.ws.current_version
        self.assertEqual(version.headline, "Onion prices keep spiking. Storage is why")
        self.assertEqual(version.seo["slug"], "onion-prices-storage")
        self.assertEqual(self.ws.findings.count(), 2)
        self.assertEqual(list(self.ws.sources.values_list("url", flat=True)), ["https://agmarknet.gov.in/", "https://pib.gov.in/x"])
        self.assertEqual(version.source_numbers, [1, 2])
        self.assertEqual(run.web_searches, 3)

        flag_row = version.flags.get()
        self.assertEqual((flag_row.severity, flag_row.block_id), ("medium", version.body[0]["id"]))
        self.assertEqual(list(flag_row.sources.values_list("number", flat=True)), [1])
        self.assertEqual(self.ws.status, ArticleWorkspace.Status.READY)

        messages = list(self.ws.session.messages.filter(role=SessionMessage.Role.ORCHESTRATOR).values_list("content", flat=True))
        self.assertEqual(messages[0], "Researching first.")
        self.assertIn("1 flag", messages[-1])

    def test_writer_gets_the_analysis_and_outline(self):
        _run, caller = self.run_with(self.full_script())
        writer = next(r for r in caller.requests if r.agent.role == "writer")
        message = writer.messages[0]["content"]
        self.assertIn("Storage, not exports, drives the spikes", message)
        self.assertIn("<outline>", message)
        self.assertIn("Prices up 30% in a month", message)  # findings travel with the sources

    def test_researcher_links_must_have_been_retrieved(self):
        script = self.full_script(researcher=[researcher(
            ("https://agmarknet.gov.in/", "Real"), ("https://invented.example/fake", "Made up"))])
        run, _ = self.run_with(script)
        self.assertEqual(list(self.ws.findings.values_list("text", flat=True)), ["Real"])
        self.assertFalse(self.ws.sources.filter(url__contains="invented").exists())
        self.assertIn("dropped 1", run.steps.get(role="researcher").summary)

    def test_sources_to_avoid_become_blocked_domains(self):
        self.ws.sources_to_avoid = "Nothing from example-tabloid.com or opinion blogs"
        self.ws.save()
        _run, caller = self.run_with(self.full_script())
        research = next(r for r in caller.requests if r.agent.role == "researcher")
        search = next(t for t in research.tools if t.get("name") == "web_search")
        self.assertEqual(search["blocked_domains"], ["example-tabloid.com"])
        self.assertIn("record_finding", [t.get("name") for t in research.tools])


class FixLoopTests(PipelineTestCase):
    def fix_edit(self):
        return edits(BlockEdit(op="replace", block="B1", new_block=block("paragraph", "Prices rose sharply [S1].")))

    def test_serious_flags_go_back_to_the_writer_a_limited_number_of_times(self):
        script = self.full_script(
            writer=[full_draft(), self.fix_edit(), self.fix_edit()],
            fact_checker=[FactCheck(summary="x", flags=[flag()])] * 3,
        )
        run, caller = self.run_with(script)
        self.assertEqual(NewsroomAISettings.load().max_fix_rounds, 2)
        self.assertEqual(caller.roles().count("fact_checker"), 3)
        self.assertEqual(caller.roles().count("writer"), 3)
        self.assertEqual(
            [it["task"] for it in run.plan][5:], ["edit", "fact_check", "revise", "fact_check", "revise", "fact_check", "seo"]
        )
        self.assertEqual(self.ws.status, ArticleWorkspace.Status.ATTENTION)
        self.assertEqual(self.ws.open_high_flags().count(), 1)
        fix = next(r for r in caller.requests if r.agent.role == "writer" and "Return only the edits" in r.messages[0]["content"])
        self.assertIn("Blocks to work on: B1.", fix.messages[0]["content"])

    def test_a_fix_that_works_ends_ready(self):
        script = self.full_script(
            writer=[full_draft(), self.fix_edit()],
            fact_checker=[FactCheck(summary="x", flags=[flag()]), clean_check()],
        )
        self.run_with(script)
        self.assertEqual(self.ws.status, ArticleWorkspace.Status.READY)
        self.assertIn("Prices rose sharply", self.ws.current_version.body[0]["value"])

    def test_claims_the_editor_accepted_are_not_flagged_again(self):
        version = self.make_version(self.ws)
        FactCheckFlag.objects.create(workspace=self.ws, version=version, claim="Prices rose 30% in a month",
                                     severity="high", issue="x", status=FactCheckFlag.Status.DISMISSED)
        script = self.full_script(fact_checker=[FactCheck(summary="x", flags=[flag()])])
        _run, caller = self.run_with(script)
        check = next(r for r in caller.requests if r.agent.role == "fact_checker")
        self.assertIn("do not flag them again", check.messages[0]["content"])
        self.assertFalse(self.ws.current_version.flags.exists())
        self.assertEqual(self.ws.status, ArticleWorkspace.Status.READY)


class ResumeTests(PipelineTestCase):
    def test_retry_resumes_after_the_last_finished_step(self):
        script = self.full_script(analyst=[AgentError("The model declined this task.")])
        run, _ = self.run_with(script)
        self.assertEqual(run.status, AgentRun.Status.FAILED)
        self.assertIsNone(self.ws.current_version)  # no draft had been written yet

        with mock.patch("newsdesk.jobs._enqueue"):
            retry_run(run, self.editor)
        rest = self.full_script()
        for done in ("orchestrator", "researcher"):
            rest.pop(done)
        caller = ScriptedCaller(rest)
        Pipeline(run, caller=caller).execute()
        run.refresh_from_db()
        self.assertEqual(run.status, AgentRun.Status.SUCCEEDED)
        self.assertEqual(caller.roles()[0], "analyst")
        self.assertEqual(Finding.objects.filter(workspace=self.ws).count(), 2)

    def test_a_draft_written_before_a_failure_is_kept(self):
        script = self.full_script(editor=[AgentError("Overloaded for too long.")])
        run, _ = self.run_with(script)
        self.assertEqual(run.status, AgentRun.Status.FAILED)
        version = self.ws.current_version
        self.assertIsNotNone(version)
        self.assertIn("has not been through every step", version.change_summary)


class RevisionPlanTests(PipelineTestCase):
    def test_headline_only_revision_keeps_flags_on_unchanged_text(self):
        version = self.make_version(self.ws, body=[paragraph("Prices rose 30% in a month [S1]."), heading("Why")])
        kept = FactCheckFlag.objects.create(workspace=self.ws, version=version, block_id=version.body[0]["id"],
                                            claim="30%", severity="medium", issue="Check period")
        trigger = SessionMessage.objects.create(session=self.ws.session, role="editor", content="Punchier headline please",
                                                status="open")
        run, caller = self.run_with({"orchestrator": [plan("seo")], "seo": [seo("Onions: the storage problem")]},
                                    kind=AgentRun.Kind.REVISE, trigger=trigger)
        self.assertEqual(caller.roles(), ["orchestrator", "seo"])  # no fact-check: the text didn't change
        self.assertIn("Punchier headline please", caller.requests[0].messages[0]["content"])
        new = self.ws.current_version
        self.assertEqual((new.number, new.headline), (2, "Onions: the storage problem"))
        self.assertEqual(new.body, version.body)
        self.assertEqual(new.flags.get().claim, kept.claim)

    def test_targeted_revision_is_followed_by_a_fact_check(self):
        self.make_version(self.ws)
        trigger = SessionMessage.objects.create(session=self.ws.session, role="editor", content="Soften the opening")
        run, caller = self.run_with(
            {"orchestrator": [plan("revise", blocks=["B1"])],
             "writer": [edits(BlockEdit(op="replace", block="B1", new_block=block("paragraph", "Prices rose [S1].")))],
             "fact_checker": [clean_check()]},
            kind=AgentRun.Kind.REVISE, trigger=trigger,
        )
        self.assertEqual(caller.roles(), ["orchestrator", "writer", "fact_checker"])


class PlanningTests(WorkspaceTestCase):
    def steps(self, *tasks):
        return [PlanStep(task=t, instructions=t, blocks=[]) for t in tasks]

    def test_new_drafts_always_write_in_order_with_a_fact_check(self):
        active = set(AgentDefinition.objects.values_list("role", flat=True))
        items = planning.validate(self.steps("seo", "write", "research", "revise"), fresh=True, active_roles=active)
        self.assertEqual([i["task"] for i in items], ["research", "write", "fact_check", "seo"])
        fallback = planning.validate(self.steps("research"), fresh=True, active_roles=active)
        self.assertEqual([i["task"] for i in fallback], ["research", "analyse", "outline", "write", "edit", "fact_check", "seo"])

    def test_inactive_agents_are_skipped_and_revisions_keep_their_order(self):
        active = set(AgentDefinition.objects.values_list("role", flat=True)) - {"analyst"}
        items = planning.validate(self.steps("analyse", "edit", "revise", "seo"), fresh=False, active_roles=active)
        self.assertEqual([i["task"] for i in items], ["edit", "revise", "fact_check", "seo"])
        self.assertEqual(planning.validate(self.steps("seo"), fresh=False, active_roles=active)[0]["task"], "seo")


class ApplyEditsTests(WorkspaceTestCase):
    def draft(self):
        return {
            "headline": "H", "dek": "D", "tags": [], "seo": {}, "source_numbers": [1],
            "body": [paragraph("One [S1].", "a"), heading("Two", "b"),
                     {"type": "image", "value": 5, "id": "c"}, paragraph("Four.", "d")],
        }

    def test_untouched_blocks_stay_identical(self):
        draft = self.draft()
        new, skipped = drafts.apply_edits(draft, edits(
            BlockEdit(op="replace", block="B4", new_block=block("paragraph", "Four, better [S2] [S9]."))
        ), known={1, 2})
        self.assertEqual(new["body"][:3], draft["body"][:3])
        self.assertEqual(new["body"][3]["id"], "d")
        self.assertIn("Four, better [S2].", new["body"][3]["value"])
        self.assertNotIn("S9", new["body"][3]["value"])
        self.assertEqual(new["source_numbers"], [1, 2])
        self.assertEqual(skipped, [])

    def test_insert_delete_and_protected_blocks(self):
        new, skipped = drafts.apply_edits(self.draft(), edits(
            BlockEdit(op="insert_after", block="B0", new_block=block("paragraph", "New opening.")),
            BlockEdit(op="delete", block="B2", new_block=block("paragraph", "")),
            BlockEdit(op="replace", block="B3", new_block=block("paragraph", "Not an image")),
            BlockEdit(op="replace", block="B9", new_block=block("paragraph", "Nowhere")),
            headline="New headline",
        ), known={1})
        self.assertEqual([b["id"] for b in new["body"]][1:], ["a", "c", "d"])
        self.assertNotIn(new["body"][0]["id"], {"a", "b", "c", "d"})
        self.assertEqual(new["headline"], "New headline")
        self.assertEqual(len(skipped), 2)

    def test_an_empty_article_is_refused(self):
        draft = {"headline": "H", "dek": "D", "tags": [], "seo": {}, "source_numbers": [], "body": [paragraph("Only.", "a")]}
        with self.assertRaises(ValueError):
            drafts.apply_edits(draft, edits(BlockEdit(op="delete", block="B1", new_block=block("paragraph", ""))), known=set())


class IsolationTests(PipelineTestCase):
    def test_one_articles_session_never_reaches_another(self):
        other = self.make_workspace(self.make_topic("Health budget cuts", desk=self.health),
                                    brief="Why state health budgets are shrinking.",
                                    sources_to_use="https://health.example/report Health report")
        a_run, _ = self.run_with(self.full_script())
        SessionMessage.objects.create(session=self.ws.session, role="editor", content="SECRET-A feedback")
        b_script = self.full_script(
            researcher=[researcher(("https://health.example/report", "Budgets fell 8%"))],
            analyst=[Analysis(thesis="Budgets are shrinking [S1].", context="c", perspectives=[], implications="i", uncertainties="u")],
            outliner=[Outline(headline_options=["Health budgets shrink"], standfirst="s", sections=[], extras=[])],
            writer=[full_draft(headline="Health budgets shrink", standfirst="States spend less.",
                               body=[block("paragraph", "Budgets fell 8% [S1].")], tags=["Health"])],
            seo=[seo("Health budgets are shrinking")],
        )
        _b_run, b_caller = self.run_with(b_script, workspace=other)
        everything = "\n".join(
            str(r.messages) + "".join(block["text"] for block in r.system) for r in b_caller.requests
        )
        for leak in ("onion", "agmarknet", "SECRET-A", "Prices up 30%", "Storage, not exports"):
            self.assertNotIn(leak.lower(), everything.lower())
        self.assertIn("Health budget cuts", everything)
        self.assertEqual(other.sources.count(), 1)  # the editor's link, reused by the researcher


@override_settings(NEWSDESK_WRITER="fake")
class FakePipelineTests(PipelineTestCase):
    def test_the_whole_pipeline_runs_offline(self):
        with mock.patch("newsdesk.jobs._enqueue"):
            run = start_run(self.ws, AgentRun.Kind.GENERATE, self.editor)
        Pipeline(run, caller=FakeCaller()).execute()
        run.refresh_from_db()
        self.ws.refresh_from_db()
        self.assertEqual(run.status, AgentRun.Status.SUCCEEDED)
        self.assertEqual(run.steps.count(), 8)
        self.assertEqual(self.ws.status, ArticleWorkspace.Status.READY)
        self.assertGreaterEqual(self.ws.sources.count(), 2)
        self.assertEqual(self.ws.current_version.source_numbers[:1], [1])
        self.assertEqual(self.ws.current_version.flags.get().severity, "low")

        trigger = SessionMessage.objects.create(session=self.ws.session, role="editor", content="Shorter opening")
        with mock.patch("newsdesk.jobs._enqueue"):
            revision = start_run(self.ws, AgentRun.Kind.REVISE, self.editor, trigger=trigger)
        Pipeline(revision, caller=FakeCaller()).execute()
        self.ws.refresh_from_db()
        self.assertEqual(self.ws.current_version.number, 2)
        self.assertIn("[demo revision]", self.ws.current_version.body[0]["value"])

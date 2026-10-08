"""Run one AgentRun: its plan, step by step, then a new version of the article.

Every run starts with the orchestrator, which plans the remaining steps
(planning.py checks the plan; steps.py holds what each agent does). The plan
can grow while the run goes: the fact-checker sends serious flags back to the
writer for a limited number of rounds.

Each step's output (including the working draft) is saved as it finishes, so
a run that fails part-way can be retried from the failed step, and a
finished draft is never lost: if the run cannot complete, the latest draft is
still saved as a version, marked as unfinished.
"""

import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from newsdesk.models import AgentDefinition, AgentRun, AgentStep, SessionMessage
from newsdesk.pagesync import import_page_edits, sync_page
from newsdesk.versions import create_version

from . import drafts, planning
from .context import build_system, record_editor_sources
from .events import RUN_END, TextBuffer, emit
from .llm import AgentError, AgentRequest, TransientAgentError, estimate_cost, get_caller
from .steps import AgentSteps

logger = logging.getLogger(__name__)


class RunCancelled(Exception):
    pass


class Pipeline(AgentSteps):
    def __init__(self, run, caller=None):
        self.run = run
        self.workspace = run.workspace
        self.caller = caller or get_caller()

    # -- entry point -----------------------------------------------------------

    def execute(self):
        run = self.run
        with transaction.atomic():
            locked = AgentRun.objects.select_for_update().get(pk=run.pk)
            if locked.status != AgentRun.Status.QUEUED:
                return locked.status
            locked.status = AgentRun.Status.RUNNING
            locked.started_at = locked.started_at or timezone.now()
            locked.error = ""
            locked.save(update_fields=["status", "started_at", "error"])
        run.refresh_from_db()
        self.workspace.refresh_status()
        emit(run, "status", "Agents started")

        import_page_edits(self.workspace, run.requested_by)
        self.workspace.refresh_from_db()
        record_editor_sources(self.workspace)

        try:
            if not run.plan:
                run.plan = self.make_plan()
                run.save(update_fields=["plan"])
            draft = self.run_steps()
            self.finish(draft)
        except RunCancelled:
            emit(run, RUN_END, "Run cancelled")
            self.workspace.refresh_status()
        except TransientAgentError:
            raise  # the Celery task decides whether to retry
        except AgentError as exc:
            self.fail(str(exc))
        except Exception:
            logger.exception("Agent run %s failed unexpectedly", run.pk)
            self.fail("Unexpected error while the agents were working; see the worker log.")
            raise
        return self.run.status

    # -- planning --------------------------------------------------------------

    def make_plan(self):
        """Every run starts with the orchestrator, which plans the rest."""
        return [planning.item("plan", "Plan the work.")]

    def step_for(self, sequence):
        step = self.run.steps.filter(sequence=sequence).first()
        if step is None:
            item = self.run.plan[sequence - 1]
            step = AgentStep.objects.create(
                run=self.run, sequence=sequence, role=item["role"], instructions=item.get("instructions", "")
            )
        return step

    def run_steps(self):
        """Run the plan in order. The plan may grow as steps run (orchestrator, fix rounds)."""
        draft = drafts.from_version(self.workspace.current_version)
        sequence = 1
        while sequence <= len(self.run.plan):
            step = self.step_for(sequence)
            if step.status == AgentStep.Status.SUCCEEDED:
                draft = (step.output or {}).get("draft", draft)
            elif step.status != AgentStep.Status.SKIPPED:
                self.check_cancelled()
                draft = self.run_step(step, draft)
            self.run.refresh_from_db(fields=["plan"])
            sequence += 1
        return draft

    def check_cancelled(self):
        status = AgentRun.objects.filter(pk=self.run.pk).values_list("status", flat=True).first()
        if status == AgentRun.Status.CANCELLED:
            raise RunCancelled

    # -- steps -----------------------------------------------------------------

    def run_step(self, step, draft):
        task = self.run.plan[step.sequence - 1].get("task", step.role)
        handler = getattr(self, f"step_{task}", None)
        if handler is None:
            raise AgentError(f"No handler for the {step.role} step.")
        step.status = AgentStep.Status.RUNNING
        step.attempts += 1
        step.started_at = timezone.now()
        step.error = ""
        step.save(update_fields=["status", "attempts", "started_at", "error"])
        label = planning.LABELS.get(task, task)
        emit(self.run, "step", f"{step.role.replace('_', ' ').capitalize()}: {label} started", step=step)
        try:
            draft = handler(step, draft)
        except AgentError as exc:
            step.status = AgentStep.Status.FAILED
            step.error = str(exc)
            step.finished_at = timezone.now()
            step.save()
            emit(self.run, "error", str(exc), step=step)
            raise
        step.status = AgentStep.Status.SUCCEEDED
        step.finished_at = timezone.now()
        if draft is not None:
            step.output = {**(step.output or {}), "draft": draft}
        step.save()
        emit(self.run, "step_done", step.summary or "Done", step=step)
        return draft

    def call(self, step, role, messages, output_format=None, tools=(), tool_handlers=None, input_summary=""):
        """Call one agent for a step, recording model, usage and cost on the step and the run."""
        agent = AgentDefinition.for_role(role)
        step.agent, step.model = agent, agent.model
        step.input_summary = input_summary
        text = TextBuffer(self.run, step)

        def on_event(kind, message, data=None):
            if kind == "text":
                text.add(message)
            else:
                text.flush()
                emit(self.run, kind, message, step=step, data=data)

        request = AgentRequest(
            agent=agent,
            system=build_system(agent, self.workspace),
            messages=messages,
            output_format=output_format,
            tools=list(tools),
            tool_handlers=tool_handlers or {},
            on_event=on_event,
        )
        try:
            response = self.caller.call(request)
        finally:
            text.flush()
        return self._record(step, response)

    def _record(self, step, response):
        usage = response.usage
        step.model = response.model
        step.input_tokens += usage.input_tokens
        step.output_tokens += usage.output_tokens
        step.cache_read_tokens += usage.cache_read_tokens
        step.cache_write_tokens += usage.cache_write_tokens
        step.web_searches += usage.web_searches
        cost = estimate_cost(response.model, usage)
        step.cost += cost
        step.save()
        AgentRun.objects.filter(pk=self.run.pk).update(
            input_tokens=F("input_tokens") + usage.input_tokens,
            output_tokens=F("output_tokens") + usage.output_tokens,
            cache_read_tokens=F("cache_read_tokens") + usage.cache_read_tokens,
            cache_write_tokens=F("cache_write_tokens") + usage.cache_write_tokens,
            web_searches=F("web_searches") + usage.web_searches,
            cost=F("cost") + cost,
        )
        self.run.refresh_from_db()
        return response

    # -- finishing -------------------------------------------------------------

    def notes(self):
        return [
            (s.role, s.output["notes"].strip())
            for s in self.run.steps.all()
            if s.output and isinstance(s.output.get("notes"), str) and s.output["notes"].strip()
        ]

    def change_summary(self):
        summaries = [f"{s.role.replace('_', ' ').capitalize()}: {s.summary}" for s in self.run.steps.all() if s.summary]
        return "\n".join(summaries)

    def save_version(self, draft, summary):
        if draft is None or drafts.same_content(draft, self.workspace.current_version):
            return None
        version = create_version(
            self.workspace,
            headline=draft["headline"],
            dek=draft["dek"],
            body=draft["body"],
            source_numbers=draft["source_numbers"],
            tags=draft["tags"],
            seo=draft.get("seo", {}),
            run=self.run,
            user=self.run.requested_by,
            change_summary=summary,
        )
        sync_page(self.workspace, version, self.run.requested_by)
        return version

    def finish(self, draft):
        self.check_cancelled()
        version = self.save_version(draft, self.change_summary())
        flags = self.save_flags(version)
        run = self.run
        run.status = AgentRun.Status.SUCCEEDED
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])
        lines = [f"Version {version.number} is ready for your review." if version else "No changes were needed."]
        high = sum(1 for f in flags if f.severity == "high")
        if flags:
            lines.append(
                f"The fact-checker raised {len(flags)} flag{'s' if len(flags) != 1 else ''}"
                + (f", {high} serious: please check {'them' if high > 1 else 'it'} before approving." if high else ".")
            )
        for role, note in self.notes():
            lines.append(f"\n{role.replace('_', ' ').capitalize()} notes: {note}")
        SessionMessage.objects.create(
            session=self.workspace.session,
            role=SessionMessage.Role.ORCHESTRATOR,
            content="\n".join(lines).strip(),
            version=version,
            run=run,
        )
        emit(run, RUN_END, f"Finished: version {version.number} saved" if version else "Finished: no changes")
        self.workspace.refresh_status()

    def fail(self, error):
        """Give up on this run, keeping any draft a finished step produced."""
        run = self.run
        draft = None
        for step in run.steps.filter(status=AgentStep.Status.SUCCEEDED).order_by("-sequence"):
            if step.output and step.output.get("draft"):
                draft = step.output["draft"]
                break
        saved = self.save_version(
            draft,
            f"{self.change_summary()}\nThe run stopped before it finished ({error}); this draft has not been "
            "through every step.".strip(),
        )
        run.status = AgentRun.Status.FAILED
        run.error = error
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at"])
        note = f" The draft so far was saved as version {saved.number}." if saved else ""
        SessionMessage.objects.create(
            session=self.workspace.session,
            role=SessionMessage.Role.SYSTEM,
            content=f"The run failed: {error}{note} You can retry it from the activity tab.",
            run=run,
            version=saved,
        )
        emit(run, RUN_END, f"Run failed: {error}", data={"failed": True})
        self.workspace.refresh_status()



def wait_for_retry(run, error, countdown):
    """A transient error: put the run back in the queue; completed steps are kept."""
    AgentRun.objects.filter(pk=run.pk).update(status=AgentRun.Status.QUEUED, error=error)
    emit(run, "status", f"{error} Retrying in {countdown} seconds.")


def give_up(run, error):
    run.refresh_from_db()
    if run.status == AgentRun.Status.QUEUED:
        AgentRun.objects.filter(pk=run.pk).update(status=AgentRun.Status.RUNNING)
        run.refresh_from_db()
    Pipeline(run).fail(error)

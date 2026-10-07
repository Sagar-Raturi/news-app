"""Starting, retrying and cancelling agent runs. One run at a time per article."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import AgentRun, AgentStep


class ArticleBusy(Exception):
    """The agents are already working on this article."""


def _enqueue(run):
    from .tasks import run_agents

    transaction.on_commit(lambda: run_agents.delay(run.pk))


def start_run(workspace, kind, user, trigger=None):
    """Queue a run. Raises ArticleBusy if one is already queued or running."""
    try:
        with transaction.atomic():
            run = AgentRun.objects.create(workspace=workspace, kind=kind, requested_by=user, trigger=trigger)
    except IntegrityError:
        raise ArticleBusy
    workspace.refresh_status()
    _enqueue(run)
    return run


def retry_run(run, user):
    """Re-queue a failed run; finished steps are kept and the failed one runs again."""
    if run.status != AgentRun.Status.FAILED:
        return run
    try:
        with transaction.atomic():
            run.status = AgentRun.Status.QUEUED
            run.error = ""
            run.finished_at = None
            run.save(update_fields=["status", "error", "finished_at"])
            run.steps.filter(status=AgentStep.Status.FAILED).update(status=AgentStep.Status.PENDING)
    except IntegrityError:
        raise ArticleBusy
    run.workspace.refresh_status()
    _enqueue(run)
    return run


def cancel_run(run, user):
    """Stop a run after its current step. Its finished steps stay in the log."""
    updated = AgentRun.objects.filter(pk=run.pk, status__in=AgentRun.ACTIVE).update(
        status=AgentRun.Status.CANCELLED, finished_at=timezone.now()
    )
    run.refresh_from_db()
    run.workspace.refresh_status()
    return bool(updated)

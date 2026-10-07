"""The live activity feed: persisted events, plus a live channel for the page."""

from newsdesk.models import AgentEvent


def publish(workspace_id, payload):
    """Push an event to anyone watching the workspace. (Live delivery arrives with streaming.)"""


def emit(run, kind, message, step=None, data=None, persist=True):
    data = data or {}
    event = None
    if persist:
        event = AgentEvent.objects.create(run=run, step=step, kind=kind, message=message[:2000], data=data)
    publish(
        run.workspace_id,
        {
            "id": event.pk if event else None,
            "run": run.pk,
            "step": step.pk if step else None,
            "kind": kind,
            "message": message,
            "data": data,
        },
    )
    return event

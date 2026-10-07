import logging

from celery import shared_task
from django.db import transaction

from .models import DraftRequest
from .publishing import apply_revision, create_article
from .writer import DraftError, get_writer

logger = logging.getLogger(__name__)


@shared_task
def draft_article(request_id):
    """Write a commissioned draft with the desk's agent and submit it for review."""
    request = DraftRequest.objects.select_related("desk__section", "requested_by", "byline").get(pk=request_id)
    if request.status not in (DraftRequest.Status.QUEUED, DraftRequest.Status.FAILED):
        return request.status
    request.status = DraftRequest.Status.WRITING
    request.error = ""
    request.save(update_fields=["status", "error", "updated_at"])

    try:
        result = get_writer().write(request)
        with transaction.atomic():
            if request.is_revision:
                article = apply_revision(request, result)
            else:
                article = create_article(request, result)
    except (DraftError, ValueError) as exc:
        request.status = DraftRequest.Status.FAILED
        request.error = str(exc)
        request.save(update_fields=["status", "error", "updated_at"])
        return request.status
    except Exception:
        logger.exception("Draft %s failed unexpectedly", request_id)
        request.status = DraftRequest.Status.FAILED
        request.error = "Unexpected error while drafting; see the worker log."
        request.save(update_fields=["status", "error", "updated_at"])
        raise

    request.status = DraftRequest.Status.DONE
    request.article = article
    request.editor_notes = result.draft.editor_notes
    request.model_used = result.model
    request.input_tokens = result.input_tokens
    request.output_tokens = result.output_tokens
    request.cache_read_tokens = result.cache_read_tokens
    request.save()
    return request.status


RETRY_DELAYS = [30, 120, 300]


@shared_task(bind=True, max_retries=len(RETRY_DELAYS))
def run_agents(self, run_id):
    """Run an article's agents. Transient API trouble is retried from the failed step."""
    from .models import AgentRun
    from .pipeline.llm import TransientAgentError
    from .pipeline.runner import Pipeline, give_up, wait_for_retry

    run = AgentRun.objects.select_related("workspace").filter(pk=run_id).first()
    if run is None:
        return None
    try:
        return Pipeline(run).execute()
    except TransientAgentError as exc:
        if self.request.retries < self.max_retries:
            countdown = RETRY_DELAYS[self.request.retries]
            wait_for_retry(run, str(exc), countdown)
            raise self.retry(exc=exc, countdown=countdown)
        give_up(run, f"{exc} Gave up after {self.max_retries} retries.")
        return AgentRun.Status.FAILED

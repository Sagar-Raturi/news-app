from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from wagtail.signals import task_rejected

from .models import DeskFeedback, DraftRequest


@receiver(post_save, sender=DraftRequest)
def enqueue_draft(sender, instance, created, **kwargs):
    """Hand new commissions to the Celery worker once the row is committed."""
    if created:
        from .tasks import draft_article

        transaction.on_commit(lambda: draft_article.delay(instance.pk))


@receiver(task_rejected)
def remember_review_feedback(sender, instance, user=None, **kwargs):
    """'Request changes' on an agent's draft becomes a memory note for that desk."""
    comment = (instance.comment or "").strip()
    if not comment:
        return
    page = instance.workflow_state.content_object
    request = (
        DraftRequest.objects.filter(article_id=getattr(page, "pk", None)).select_related("desk").first()
    )
    if request is None:
        return
    DeskFeedback.objects.create(
        desk=request.desk,
        article_type=request.article_type,
        note=comment,
        source=DeskFeedback.Source.REVIEW,
        article_id=request.article_id,
        created_by=user,
    )

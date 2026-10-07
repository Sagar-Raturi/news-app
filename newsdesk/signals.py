from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from wagtail.signals import task_rejected

from .models import ArticleNote, DraftRequest


@receiver(post_save, sender=DraftRequest)
def enqueue_draft(sender, instance, created, **kwargs):
    """Hand new commissions to the Celery worker once the row is committed."""
    if created:
        from .tasks import draft_article

        transaction.on_commit(lambda: draft_article.delay(instance.pk))


@receiver(task_rejected)
def remember_review_feedback(sender, instance, user=None, **kwargs):
    """'Request changes' on an agent's draft becomes a note on that article.

    It reaches every later revision of the article, but not other drafts from
    the desk, until an editor chooses "Make desk rule".
    """
    comment = (instance.comment or "").strip()
    if not comment:
        return
    page = instance.workflow_state.content_object
    article_id = getattr(page, "pk", None)
    if article_id is None or not DraftRequest.objects.filter(article_id=article_id).exists():
        return
    ArticleNote.remember(page, comment, ArticleNote.Source.REVIEW, user)

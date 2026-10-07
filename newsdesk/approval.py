"""Approve, publish and unpublish an AI article. Every one is an editor's click."""

from django.utils import timezone

from news.models import ArticlePage

from .models import SessionMessage
from .pagesync import import_page_edits


class NotAllowed(Exception):
    """Shown to the editor as the reason the action did not happen."""


def _note(workspace, user, text):
    SessionMessage.objects.create(
        session=workspace.session,
        role=SessionMessage.Role.SYSTEM,
        content=text,
        version=workspace.current_version,
        created_by=user,
    )


def _who(user):
    return user.get_full_name() or user.get_username()


def approve(workspace, user):
    import_page_edits(workspace, user)
    workspace.refresh_from_db()
    version = workspace.current_version
    if version is None:
        raise NotAllowed("There is no draft to approve yet.")
    if workspace.active_run():
        raise NotAllowed("The agents are still working on this article.")
    if workspace.open_high_flags().exists():
        raise NotAllowed(
            "This draft has serious fact-check flags. Fix them, or mark them as accepted, before approving."
        )
    workspace.approved_version = version
    workspace.approved_by = user
    workspace.approved_at = timezone.now()
    workspace.save(update_fields=["approved_version", "approved_by", "approved_at", "updated_at"])
    _note(workspace, user, f"{_who(user)} approved version {version.number}.")
    workspace.refresh_status()
    return version


def publish(workspace, user):
    """Publish the approved version. Fails if anything changed since approval."""
    import_page_edits(workspace, user)
    workspace.refresh_from_db()
    version = workspace.current_version
    if version is None or workspace.approved_version_id != version.pk:
        raise NotAllowed("Approve the current version before publishing it.")
    page = ArticlePage.objects.filter(pk=workspace.page_id).first()
    if page is None or version.page_revision is None:
        raise NotAllowed("This version has no page yet.")
    if not page.permissions_for_user(user).can_publish():
        raise NotAllowed("You don't have permission to publish in this section.")
    version.page_revision.publish(user=user)
    workspace.published_version = version
    workspace.published_at = timezone.now()
    workspace.save(update_fields=["published_version", "published_at", "updated_at"])
    workspace.topic.article_published()
    _note(workspace, user, f"{_who(user)} published version {version.number}.")
    workspace.refresh_status()
    return version


def unpublish(workspace, user):
    page = ArticlePage.objects.filter(pk=workspace.page_id).first()
    if page is None or not page.live:
        raise NotAllowed("This article is not live.")
    if not page.permissions_for_user(user).can_unpublish():
        raise NotAllowed("You don't have permission to unpublish this article.")
    page.unpublish(user=user)
    workspace.published_version = None
    workspace.save(update_fields=["published_version", "updated_at"])
    _note(workspace, user, f"{_who(user)} unpublished the article.")
    workspace.refresh_status()

from django import forms
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from wagtail.models import Page, TaskState

from news.models import ArticlePage

from .models import DraftRequest


class ReviseForm(forms.Form):
    instructions = forms.CharField(
        label="What should the agent change?",
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Be specific. The agent rewrites the whole draft from its source material, "
        "following these instructions and the desk's memory.",
    )


def can_revise(page, user):
    """Agent-written, unpublished drafts that this user may edit right now."""
    if page.live or not user.has_perm("newsdesk.add_draftrequest"):
        return False
    if not page.permissions_for_user(user).can_edit():
        return False
    lock = page.get_lock()
    if lock and lock.for_user(user):
        return False
    return DraftRequest.original_for(page) is not None


def latest_review_comment(page):
    state = (
        TaskState.objects.filter(
            workflow_state__base_content_type=ContentType.objects.get_for_model(Page),
            workflow_state__object_id=str(page.pk),
            status=TaskState.STATUS_REJECTED,
        )
        .exclude(comment="")
        .order_by("-finished_at")
        .first()
    )
    return state.comment if state else ""


def revise_article(request, page_id):
    page = get_object_or_404(ArticlePage, pk=page_id)
    original = DraftRequest.original_for(page)
    if original is None or not can_revise(page, request.user):
        raise PermissionDenied
    edit_url = reverse("wagtailadmin_pages:edit", args=[page.pk])
    if DraftRequest.pending_for(page):
        messages.warning(request, "The desk agent is already working on this draft.")
        return redirect(edit_url)

    form = ReviseForm(request.POST or None, initial={"instructions": latest_review_comment(page)})
    if request.method == "POST" and form.is_valid():
        DraftRequest.objects.create(
            desk=original.desk,
            article_type=original.article_type,
            brief=original.brief,
            source_material=original.source_material,
            byline=original.byline,
            revision_of=original,
            article=page,
            instructions=form.cleaned_data["instructions"],
            requested_by=request.user,
        )
        messages.success(
            request,
            f"The {original.desk.name} agent is revising '{page.title}'. "
            "It will be back in Editor review in a minute or so.",
        )
        return redirect(reverse("wagtailsnippets_newsdesk_draftrequest:list"))

    return TemplateResponse(
        request,
        "newsdesk/revise.html",
        {"page": page, "desk": original.desk, "form": form, "edit_url": edit_url, "memory_size": original.desk.memory_size()},
    )

from django import forms
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from wagtail.models import Page, TaskState

from news.models import ArticlePage

from .models import ArticleNote, DraftRequest


class ReviseForm(forms.Form):
    instructions = forms.CharField(
        label="What should the agent change?",
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Be specific. The agent rewrites the whole draft from its source material, "
        "following these instructions, this article's notes and the desk's memory. "
        "The instructions are kept as a note on this article for later rounds.",
    )
    remember_for_desk = forms.BooleanField(
        required=False,
        help_text="Leave unticked for anything that only concerns this article.",
    )

    def __init__(self, *args, desk=None, article_type_label="", can_teach_desk=False, **kwargs):
        super().__init__(*args, **kwargs)
        if can_teach_desk:
            self.fields["remember_for_desk"].label = (
                f"Also remember this for all future {desk.name} {article_type_label.lower()} drafts"
            )
        else:
            del self.fields["remember_for_desk"]


class NoteForm(forms.Form):
    note = forms.CharField(
        label="Add a note for this article",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="The desk agent follows it on every revision of this article, and nowhere else.",
    )


def can_teach_desk(user):
    """Only editors (who manage desks) can turn an instruction into a desk-wide rule."""
    return user.has_perm("newsdesk.change_deskagent")


def can_manage_notes(page, user):
    """Agent-written articles this user may edit (locks don't matter: notes aren't page content)."""
    if not page.permissions_for_user(user).can_edit():
        return False
    return DraftRequest.original_for(page) is not None


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

    teach = can_teach_desk(request.user)
    form = ReviseForm(
        request.POST or None,
        initial={"instructions": latest_review_comment(page)},
        desk=original.desk,
        article_type_label=original.get_article_type_display(),
        can_teach_desk=teach,
    )
    if request.method == "POST" and form.is_valid():
        instructions = form.cleaned_data["instructions"]
        # Saved before the commission so the agent's run sees the same notes and memory.
        note = ArticleNote.remember(page, instructions, ArticleNote.Source.REVISION, request.user)
        if teach and form.cleaned_data.get("remember_for_desk") and note:
            note.promote(original.desk, original.article_type, request.user)
        DraftRequest.objects.create(
            desk=original.desk,
            article_type=original.article_type,
            brief=original.brief,
            source_material=original.source_material,
            byline=original.byline,
            revision_of=original,
            article=page,
            instructions=instructions,
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
        {
            "page": page,
            "desk": original.desk,
            "form": form,
            "edit_url": edit_url,
            "memory_size": len(original.desk.memory(original.article_type)),
            "notes": ArticleNote.standing(page),
            "notes_url": reverse("newsdesk_article_notes", args=[page.pk]),
        },
    )


def article_notes(request, page_id):
    """One article's memory: list, add, forget/restore, and promote to a desk rule."""
    page = get_object_or_404(ArticlePage, pk=page_id)
    original = DraftRequest.original_for(page)
    if original is None or not can_manage_notes(page, request.user):
        raise PermissionDenied
    url = reverse("newsdesk_article_notes", args=[page.pk])
    teach = can_teach_desk(request.user)
    form = NoteForm()

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            form = NoteForm(request.POST)
            if form.is_valid():
                ArticleNote.remember(page, form.cleaned_data["note"], ArticleNote.Source.MANUAL, request.user)
                messages.success(request, "Note added. The agent will follow it on every revision of this article.")
                return redirect(url)
        else:
            note = get_object_or_404(ArticleNote, pk=request.POST.get("note"), article_id=page.pk)
            if action == "forget":
                note.active = False
                note.save(update_fields=["active"])
                messages.success(request, "The agent will no longer see this note.")
            elif action == "restore":
                note.active = True
                note.save(update_fields=["active"])
                messages.success(request, "The agent will follow this note again.")
            elif action == "promote":
                if not teach:
                    raise PermissionDenied
                note.promote(original.desk, original.article_type, request.user)
                messages.success(
                    request,
                    f"Added to the {original.desk.name}'s memory for all future "
                    f"{original.get_article_type_display().lower()} drafts.",
                )
            return redirect(url)

    return TemplateResponse(
        request,
        "newsdesk/article_notes.html",
        {
            "page": page,
            "desk": original.desk,
            "type_label": original.get_article_type_display(),
            "notes": ArticleNote.objects.filter(article_id=page.pk).select_related("created_by", "desk_rule"),
            "form": form,
            "can_teach": teach,
            "edit_url": reverse("wagtailadmin_pages:edit", args=[page.pk]),
            "revise_url": reverse("newsdesk_revise", args=[page.pk]) if can_revise(page, request.user) else "",
            "desk_url": reverse("wagtailsnippets_newsdesk_deskagent:edit", args=[original.desk.pk]) if teach else "",
        },
    )

"""The AI article workspace in the Wagtail admin: one page per article.

Every view here also works as a plain full-page request (forms POST and
redirect); the page's JavaScript only switches tabs and refreshes panels.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from .diff import diff_versions
from .forms import BriefForm, NewArticleForm
from .models import ArticleWorkspace, Topic
from .rendering import render_version
from .versions import open_flags, restore_version

TABS = ["brief", "activity", "feedback", "versions"]


def can_view(user):
    return user.has_perm("newsdesk.view_articleworkspace")


def can_edit(user):
    return user.has_perm("newsdesk.change_articleworkspace")


def can_approve(user):
    return user.has_perm("newsdesk.approve_articleworkspace")


def workspace_url(workspace, tab=None, **params):
    url = reverse("newsdesk_articles:detail", args=[workspace.pk])
    if tab:
        params["tab"] = tab
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    return url


def get_workspace(request, pk, edit=False):
    if not (can_edit(request.user) if edit else can_view(request.user)):
        raise PermissionDenied
    return get_object_or_404(
        ArticleWorkspace.objects.select_related("topic", "desk__section", "current_version", "page"), pk=pk
    )


def index(request):
    if not can_view(request.user):
        raise PermissionDenied
    status = request.GET.get("status", "")
    workspaces = ArticleWorkspace.objects.select_related("topic", "desk", "current_version").annotate(
        run_cost=Sum("runs__cost"), version_count=Count("versions", distinct=True)
    )
    if status in ArticleWorkspace.Status.values:
        workspaces = workspaces.filter(status=status)
    counts = dict(ArticleWorkspace.objects.values_list("status").annotate(n=Count("pk")))
    return TemplateResponse(
        request,
        "newsdesk/workspace/index.html",
        {
            "workspaces": workspaces,
            "status": status,
            "statuses": [(value, label, counts.get(value, 0)) for value, label in ArticleWorkspace.Status.choices],
            "suggested_topics": Topic.objects.filter(status=Topic.Status.SUGGESTED).count(),
            "can_create": request.user.has_perm("newsdesk.add_articleworkspace"),
        },
    )


def create(request):
    if not request.user.has_perm("newsdesk.add_articleworkspace"):
        raise PermissionDenied
    initial = {"article_type": "analysis"}
    topic_id = request.GET.get("topic")
    if topic_id and topic_id.isdigit():
        topic = Topic.objects.filter(pk=topic_id).first()
        if topic:
            initial.update(topic=topic, desk=topic.desk)
    form = NewArticleForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        workspace = form.save(request.user)
        messages.success(request, "Article created. Check the brief, then click Generate.")
        return redirect(workspace_url(workspace, tab="brief"))
    return TemplateResponse(request, "newsdesk/workspace/new.html", {"form": form})


def detail(request, pk):
    return render_detail(request, get_workspace(request, pk))


def render_detail(request, workspace, tab=None, brief_form=None):
    tab = tab or request.GET.get("tab", "")
    if tab not in TABS:
        tab = "brief" if workspace.current_version_id is None else "activity"

    versions = list(workspace.versions.select_related("created_by", "run"))
    shown = workspace.current_version
    requested = request.GET.get("v", "")
    if requested.isdigit():
        shown = next((v for v in versions if v.number == int(requested)), shown)

    compare = None
    if request.GET.get("compare", "").isdigit():
        new = next((v for v in versions if v.number == int(request.GET["compare"])), None)
        old_number = request.GET.get("against", "")
        old = None
        if new is not None:
            if old_number.isdigit():
                old = next((v for v in versions if v.number == int(old_number)), None)
            else:
                old = next((v for v in versions if v.number < new.number), None)
        if new and old:
            compare = {"old": old, "new": new, "diff": diff_versions(old, new)}
            shown = new

    return TemplateResponse(
        request,
        "newsdesk/workspace/detail.html",
        {
            "workspace": workspace,
            "tab": tab,
            "tabs": TABS,
            "versions": versions,
            "shown": shown,
            "is_current": shown is not None and shown.pk == workspace.current_version_id,
            "draft": render_version(shown) if shown else None,
            "flags": open_flags(shown) if shown else [],
            "compare": compare,
            "brief_form": brief_form or BriefForm(instance=workspace),
            "can_edit": can_edit(request.user),
            "can_approve": can_approve(request.user),
            "messages_list": list(workspace.session.messages.select_related("created_by")),
            "edit_page_url": reverse("wagtailadmin_pages:edit", args=[workspace.page_id]) if workspace.page_id else "",
        },
    )


@require_POST
def save_brief(request, pk):
    workspace = get_workspace(request, pk, edit=True)
    form = BriefForm(request.POST, instance=workspace)
    if form.is_valid():
        form.save()
        messages.success(request, "Brief saved. It applies to the next run.")
        return redirect(workspace_url(workspace, tab="brief"))
    return render_detail(request, workspace, tab="brief", brief_form=form)


@require_POST
def restore(request, pk, number):
    workspace = get_workspace(request, pk, edit=True)
    version = get_object_or_404(workspace.versions, number=number)
    if workspace.active_run():
        messages.warning(request, "The agents are working on this article. Restore when they have finished.")
        return redirect(workspace_url(workspace, tab="versions"))
    if version.pk == workspace.current_version_id:
        messages.info(request, "That is already the current version.")
        return redirect(workspace_url(workspace, tab="versions"))
    restored = restore_version(workspace, version, request.user)
    messages.success(request, f"Version {version.number} restored as version {restored.number}.")
    return redirect(workspace_url(workspace, tab="versions"))

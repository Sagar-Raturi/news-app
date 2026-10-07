from django.urls import path, reverse
from wagtail import hooks
from wagtail.admin.action_menu import ActionMenuItem
from wagtail.admin.widgets import PageListingButton
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from news.models import ArticlePage

from . import views
from .models import DeskAgent, DraftRequest


class DeskAgentViewSet(SnippetViewSet):
    model = DeskAgent
    icon = "user"
    menu_label = "Desk agents"
    list_display = ["name", "section", "memory_size", "model", "active"]
    list_filter = ["active"]
    search_fields = ["name"]


class DraftRequestViewSet(SnippetViewSet):
    model = DraftRequest
    icon = "edit"
    menu_label = "Commission a draft"
    list_display = ["created_at", "desk", "type_label", "short_brief", "status_label", "article_link"]
    list_filter = ["status", "desk", "article_type"]
    inspect_view_enabled = True
    inspect_view_fields = [
        "desk",
        "article_type",
        "status",
        "article",
        "editor_notes",
        "error",
        "instructions",
        "brief",
        "article_instructions",
        "source_material",
        "byline",
        "requested_by",
        "model_used",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "created_at",
    ]


class NewsdeskGroup(SnippetViewSetGroup):
    menu_label = "Newsdesk AI"
    menu_icon = "draft"
    menu_order = 150
    items = (DraftRequestViewSet, DeskAgentViewSet)


register_snippet(NewsdeskGroup)


@hooks.register("register_admin_urls")
def register_newsdesk_urls():
    return [
        path("newsdesk/revise/<int:page_id>/", views.revise_article, name="newsdesk_revise"),
        path("newsdesk/notes/<int:page_id>/", views.article_notes, name="newsdesk_article_notes"),
    ]


@hooks.register("register_page_header_buttons")
def newsdesk_buttons(page, user, view_name, next_url=None):
    specific = page.specific
    if isinstance(specific, ArticlePage) and views.can_revise(specific, user):
        yield PageListingButton(
            "Revise with AI",
            url=reverse("newsdesk_revise", args=[page.pk]),
            icon_name="draft",
            priority=35,
        )
    if isinstance(specific, ArticlePage) and views.can_manage_notes(specific, user):
        yield PageListingButton(
            "Article notes",
            url=reverse("newsdesk_article_notes", args=[page.pk]),
            icon_name="list-ul",
            priority=36,
        )


class ReviseWithAIMenuItem(ActionMenuItem):
    """'Revise with AI' in the save/publish menu at the bottom of the edit screen."""

    label = "Revise with AI"
    name = "action-revise-with-ai"
    icon_name = "draft"

    def is_shown(self, context):
        page = context.get("page")
        if context["view"] != "edit" or page is None:
            return False
        specific = page.specific
        return isinstance(specific, ArticlePage) and views.can_revise(specific, context["request"].user)

    def get_url(self, parent_context):
        return reverse("newsdesk_revise", args=[parent_context["page"].pk])


@hooks.register("register_page_action_menu_item")
def register_revise_menu_item():
    return ReviseWithAIMenuItem(order=45)

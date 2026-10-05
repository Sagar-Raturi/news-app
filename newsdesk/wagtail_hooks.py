from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

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
        "brief",
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

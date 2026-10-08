from wagtail import hooks
from wagtail.admin.ui.components import Component

from core.launch import MANUAL_CHECKS, launch_checks
from core.newsroom import EDITORS


class LaunchChecklistPanel(Component):
    """Dashboard panel listing what is still missing before a public launch."""

    name = "launch_checklist"
    order = 50
    template_name = "core/admin/launch_checklist_panel.html"

    def get_context_data(self, parent_context=None):
        checks = launch_checks()
        return {"checks": checks, "missing": [c for c in checks if not c.ok], "manual": MANUAL_CHECKS}


@hooks.register("construct_homepage_panels")
def add_launch_checklist(request, panels):
    user = request.user
    if user.is_superuser or user.groups.filter(name=EDITORS).exists():
        panels.append(LaunchChecklistPanel())

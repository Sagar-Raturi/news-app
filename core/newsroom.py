"""Idempotent setup of the site structure, newsroom roles and review workflow.

Used by the `bootstrap_site` management command (run on every container
start) and by tests, so there is a single source of truth.
"""

from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.db import transaction
from wagtail.models import (
    Collection,
    GroupApprovalTask,
    GroupCollectionPermission,
    GroupPagePermission,
    Page,
    Site,
    Workflow,
    WorkflowPage,
    WorkflowTask,
)

from core.models import StandardPage
from news.models import HomePage, SectionPage
from newsdesk.desks import STARTER_DESKS
from newsdesk.models import AgentDefinition, DeskAgent, ModelPrice
from newsdesk.roles import DEFAULT_MODEL, STARTER_AGENTS, starter_prices

WRITERS = "Writers"
EDITORS = "Editors"
WORKFLOW_NAME = "Newsroom review"
TASK_NAME = "Editor review"

# (title, slug, intro, show_on_homepage)
SECTIONS = [
    ("Politics", "politics", "Parliament, parties, elections and the business of governing India.", True),
    ("International", "international", "India in the world: diplomacy, trade, security and the diaspora.", True),
    ("Local", "local", "Cities, towns and districts — the decisions that shape daily life.", True),
    ("Economy", "economy", "Growth, jobs, prices, markets and the policies behind them.", True),
    ("Society", "society", "How Indians live, work and change: culture, rights and communities.", True),
    ("Education", "education", "Schools, universities, exams and the skills India needs.", True),
    ("Health", "health", "Public health, hospitals, medicine and wellbeing.", True),
    ("Science & Tech", "science-tech", "Space, research, digital India and the technology economy.", True),
    ("Opinion", "opinion", "Columns, arguments and the editorial view.", False),
]

ABOUT_SLUG = "about"
ABOUT_TITLE = "About & AI policy"

# "add" lets writers create pages and edit/delete their own drafts, but not
# colleagues' pages; Editors can edit anything.
WRITER_PAGE_PERMS = ["add_page"]
EDITOR_PAGE_PERMS = ["add_page", "change_page", "publish_page", "bulk_delete_page", "lock_page", "unlock_page"]
WRITER_COLLECTION_PERMS = [
    ("wagtailimages", "add_image"),
    ("wagtailimages", "choose_image"),
    ("wagtaildocs", "add_document"),
    ("wagtaildocs", "choose_document"),
]
EDITOR_COLLECTION_PERMS = WRITER_COLLECTION_PERMS + [
    ("wagtailimages", "change_image"),
    ("wagtailimages", "delete_image"),
    ("wagtaildocs", "change_document"),
    ("wagtaildocs", "delete_document"),
]
WRITER_MODEL_PERMS = [
    ("wagtailadmin", "access_admin"),
    ("news", "view_author"),
    # Writers can commission AI drafts and read the desks' style guides.
    ("newsdesk", "add_draftrequest"),
    ("newsdesk", "view_draftrequest"),
    ("newsdesk", "view_deskagent"),
    # AI article workspaces: writers create topics and briefs and give feedback.
    ("newsdesk", "add_topic"),
    ("newsdesk", "change_topic"),
    ("newsdesk", "view_topic"),
    ("newsdesk", "add_articleworkspace"),
    ("newsdesk", "change_articleworkspace"),
    ("newsdesk", "view_articleworkspace"),
    ("newsdesk", "view_agentdefinition"),
]
EDITOR_MODEL_PERMS = WRITER_MODEL_PERMS + [
    ("news", "add_author"),
    ("news", "change_author"),
    ("news", "delete_author"),
    ("core", "change_sitesettings"),
    # Editors configure the desk agents and their memory.
    ("newsdesk", "add_deskagent"),
    ("newsdesk", "change_deskagent"),
    ("newsdesk", "delete_deskagent"),
    # Only editors approve and publish AI articles, and configure the agents.
    ("newsdesk", "approve_articleworkspace"),
    ("newsdesk", "delete_topic"),
    ("newsdesk", "change_agentdefinition"),
    ("newsdesk", "view_modelprice"),
    ("newsdesk", "change_modelprice"),
    ("newsdesk", "change_newsroomaisettings"),
]


def _perm(app_label, codename):
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def ensure_home_page():
    home = HomePage.objects.first()
    if home is None:
        root = Page.get_first_root_node()
        # Remove Wagtail's placeholder "Welcome" page if it is still there.
        for page in root.get_children().filter(content_type__model="page", content_type__app_label="wagtailcore"):
            page.delete()
        root.refresh_from_db()
        home = root.add_child(
            instance=HomePage(title="The Ledger", slug="home", intro="News, analysis and argument from India")
        )
        home.save_revision().publish()
    # Match the Wagtail Site to SITE_BASE_URL so page.full_url (canonical
    # links, sitemaps) points at the public origin, including the port.
    base = urlsplit(settings.SITE_BASE_URL)
    port = base.port or (443 if base.scheme == "https" else 80)
    site = Site.objects.filter(is_default_site=True).first()
    if site is None:
        site = Site(is_default_site=True, site_name="The Ledger")
    site.hostname = base.hostname or "localhost"
    site.port = port
    site.root_page = home
    site.save()
    return home


def ensure_sections(home):
    sections = []
    for title, slug, intro, on_home in SECTIONS:
        section = SectionPage.objects.child_of(home).filter(slug=slug).first()
        if section is None:
            section = home.add_child(
                instance=SectionPage(title=title, slug=slug, intro=intro, show_on_homepage=on_home, show_in_menus=True)
            )
            section.save_revision().publish()
        sections.append(section)
    return sections


def ensure_about_page(home):
    about = StandardPage.objects.child_of(home).filter(slug=ABOUT_SLUG).first()
    if about is None:
        about = home.add_child(instance=StandardPage(title=ABOUT_TITLE, slug=ABOUT_SLUG))
        about.save_revision().publish()
    return about


def _set_group_permissions(group, home, page_perms, collection_perms, model_perms):
    wanted = {_perm("wagtailcore", codename) for codename in page_perms}
    GroupPagePermission.objects.filter(group=group, page=home).exclude(permission__in=wanted).delete()
    for permission in wanted:
        GroupPagePermission.objects.get_or_create(group=group, page=home, permission=permission)

    root_collection = Collection.get_first_root_node()
    for app_label, codename in collection_perms:
        GroupCollectionPermission.objects.get_or_create(
            group=group, collection=root_collection, permission=_perm(app_label, codename)
        )

    group.permissions.add(*[_perm(app_label, codename) for app_label, codename in model_perms])


def ensure_groups(home):
    writers, _ = Group.objects.get_or_create(name=WRITERS)
    editors, _ = Group.objects.get_or_create(name=EDITORS)
    # Wagtail ships a "Moderators" group; our Editors take over that role.
    Group.objects.filter(name="Moderators").delete()
    # Wagtail's default "Editors" group has page permissions on the tree root;
    # ours are scoped to the site's home page instead.
    for group in (writers, editors):
        GroupPagePermission.objects.filter(group=group).exclude(page=home).delete()
    _set_group_permissions(writers, home, WRITER_PAGE_PERMS, WRITER_COLLECTION_PERMS, WRITER_MODEL_PERMS)
    _set_group_permissions(editors, home, EDITOR_PAGE_PERMS, EDITOR_COLLECTION_PERMS, EDITOR_MODEL_PERMS)
    return writers, editors


def ensure_workflow(home, editors):
    task = GroupApprovalTask.objects.filter(name=TASK_NAME).first()
    if task is None:
        task = GroupApprovalTask.objects.create(name=TASK_NAME)
    task.groups.set([editors])
    if not task.active:
        task.active = True
        task.save()

    workflow, _ = Workflow.objects.get_or_create(name=WORKFLOW_NAME, defaults={"active": True})
    if not workflow.active:
        workflow.active = True
        workflow.save()
    WorkflowTask.objects.get_or_create(workflow=workflow, task=task, defaults={"sort_order": 0})

    # Replace Wagtail's default "Moderators approval" workflow everywhere.
    for other in Workflow.objects.exclude(pk=workflow.pk).filter(active=True):
        other.deactivate()
    WorkflowPage.objects.exclude(workflow=workflow).delete()
    WorkflowPage.objects.update_or_create(page=home, defaults={"workflow": workflow})
    return workflow


def ensure_desks(sections):
    """Create the starter desk agents once; editors' later changes are kept."""
    by_slug = {s.slug: s for s in sections}
    desks = []
    for slug, name, section_slug, style_guide in STARTER_DESKS:
        if section_slug not in by_slug:
            continue
        desk, _ = DeskAgent.objects.get_or_create(
            slug=slug, defaults={"name": name, "section": by_slug[section_slug], "style_guide": style_guide}
        )
        desks.append(desk)
    return desks


def ensure_agents():
    """Create the pipeline's agents; refresh starter prompts nobody has edited."""
    agents = []
    for role, name, description, prompt, effort, max_tokens, search, fetch, uses in STARTER_AGENTS:
        defaults = {
            "name": name,
            "description": description,
            "system_prompt": prompt,
            "model": DEFAULT_MODEL,
            "effort": effort,
            "max_tokens": max_tokens,
            "web_search": search,
            "web_fetch": fetch,
            "max_web_uses": uses or 8,
        }
        agent, created = AgentDefinition.objects.get_or_create(role=role, defaults=defaults)
        if not created and not agent.customised and agent.system_prompt != prompt:
            agent.system_prompt = prompt
            agent.description = description
            agent.save(update_fields=["system_prompt", "description", "updated_at"])
        agents.append(agent)
    return agents


def ensure_prices():
    """Starter model prices for cost estimates; editors' changes are kept."""
    for model, (inp, out, write, read) in starter_prices().items():
        ModelPrice.objects.get_or_create(
            model=model,
            defaults={
                "input_per_mtok": inp,
                "output_per_mtok": out,
                "cache_write_per_mtok": write,
                "cache_read_per_mtok": read,
            },
        )


@transaction.atomic
def bootstrap():
    home = ensure_home_page()
    sections = ensure_sections(home)
    about = ensure_about_page(home)
    writers, editors = ensure_groups(home)
    workflow = ensure_workflow(home, editors)
    desks = ensure_desks(sections)
    agents = ensure_agents()
    ensure_prices()
    return {
        "agents": agents,
        "desks": desks,
        "home": home,
        "sections": sections,
        "about": about,
        "writers": writers,
        "editors": editors,
        "workflow": workflow,
    }

"""Creating article versions. Every new draft, restore or imported hand edit goes through here."""

import copy

from django.db import transaction

from .content import ensure_ids
from .models import ArticleVersion, ArticleWorkspace, FactCheckFlag


@transaction.atomic
def create_version(
    workspace,
    *,
    headline,
    dek,
    body,
    source_numbers=(),
    tags=(),
    seo=None,
    origin=ArticleVersion.Origin.AGENT,
    user=None,
    run=None,
    change_summary="",
    based_on=None,
    page_revision=None,
):
    """Add a version, make it current and refresh the article's status."""
    caller = workspace
    # Lock the workspace row so two writers can't take the same number.
    workspace = ArticleWorkspace.objects.select_for_update().get(pk=workspace.pk)
    version = ArticleVersion.objects.create(
        workspace=workspace,
        number=workspace.next_version_number(),
        headline=headline.strip()[:255],
        dek=dek.strip()[:300],
        body=ensure_ids(copy.deepcopy(list(body))),
        source_numbers=list(source_numbers),
        tags=list(tags),
        seo=seo or {},
        origin=origin,
        created_by=user,
        run=run,
        change_summary=change_summary,
        based_on=based_on or workspace.current_version,
        page_revision=page_revision,
    )
    workspace.current_version = version
    workspace.save(update_fields=["current_version", "updated_at"])
    workspace.refresh_status()
    # Keep the caller's copy in step so a later save doesn't undo this.
    caller.current_version, caller.status = version, workspace.status
    return version


def restore_version(workspace, version, user):
    """Make an earlier version current again, as a new version (history is never rewritten)."""
    restored = create_version(
        workspace,
        headline=version.headline,
        dek=version.dek,
        body=version.body,
        source_numbers=version.source_numbers,
        tags=version.tags,
        seo=version.seo,
        origin=ArticleVersion.Origin.HUMAN,
        user=user,
        change_summary=f"Restored version {version.number}.",
        based_on=version,
    )
    # Same text, same fact-check verdicts: carry the flags over.
    for flag in version.flags.all():
        sources = list(flag.sources.all())
        flag.pk = None
        flag.version = restored
        flag.save()
        flag.sources.set(sources)
    workspace.refresh_status()
    return restored


def open_flags(version):
    """Fact-check flags on a version, most severe first."""
    flags = list(version.flags.filter(status=FactCheckFlag.Status.OPEN).prefetch_related("sources"))
    return sorted(flags, key=lambda f: (FactCheckFlag.SEVERITY_ORDER.get(f.severity, 9), f.pk))

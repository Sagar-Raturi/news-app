"""Shared fixtures for the AI article workspace tests."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.newsroom import bootstrap
from news.models import Author
from newsdesk.content import new_block_id
from newsdesk.models import ArticleVersion, ArticleWorkspace, DeskAgent, Topic

User = get_user_model()


def paragraph(text, block_id=None):
    return {"type": "paragraph", "value": f"<p>{text}</p>", "id": block_id or new_block_id()}


def heading(text, block_id=None):
    return {"type": "heading", "value": text, "id": block_id or new_block_id()}


class WorkspaceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        site = bootstrap()
        cls.site = site
        cls.economy = DeskAgent.objects.get(slug="economy")
        cls.health = DeskAgent.objects.get(slug="health")
        cls.writer = User.objects.create_user("writer", "w@example.com", "pass")
        cls.writer.groups.add(site["writers"])
        cls.editor = User.objects.create_user("editor", "e@example.com", "pass")
        cls.editor.groups.add(site["editors"])
        cls.desk_author = Author.objects.create(name="Economy Desk", slug="economy-desk")
        cls.economy.default_author = cls.desk_author
        cls.economy.save()

    def make_topic(self, title="Why onion prices keep spiking", desk=None, **kwargs):
        return Topic.objects.create(title=title, desk=desk or self.economy, created_by=self.editor, **kwargs)

    def make_workspace(self, topic=None, **kwargs):
        topic = topic or self.make_topic()
        kwargs.setdefault("brief", "Explain why onion prices keep spiking and what would fix it.")
        kwargs.setdefault("created_by", self.editor)
        return ArticleWorkspace.objects.create(topic=topic, desk=topic.desk, **kwargs)

    def make_version(self, workspace, body=None, headline="Onion prices keep spiking", **kwargs):
        version = ArticleVersion.objects.create(
            workspace=workspace,
            number=workspace.next_version_number(),
            headline=headline,
            dek=kwargs.pop("dek", "Exports, storage and the monsoon all play a part."),
            body=body if body is not None else [paragraph("Prices rose 30% in a month [S1].")],
            **kwargs,
        )
        workspace.current_version = version
        workspace.save(update_fields=["current_version", "updated_at"])
        return version

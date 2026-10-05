from django.test import SimpleTestCase, override_settings

from config.celery import app
from core.tasks import ping


class CeleryConfigTests(SimpleTestCase):
    def test_app_reads_django_settings(self):
        self.assertTrue(app.conf.broker_url.startswith("redis://"))

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_ping_task_runs(self):
        self.assertEqual(ping.apply().get(), "pong")

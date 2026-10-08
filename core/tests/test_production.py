"""Production hardening: health check, deployed-settings guards, login lockout."""

import os
import subprocess
import sys
from unittest import mock

import redis
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings

GOOD_PRODUCTION_ENV = {
    "DJANGO_ENV": "production",
    "DJANGO_SECRET_KEY": "x" * 60,
    "DJANGO_ALLOWED_HOSTS": "example.in,www.example.in",
    "SITE_BASE_URL": "https://example.in",
    "NEWSDESK_WRITER": "anthropic",
}


def load_settings(env):
    """Import the settings in a fresh interpreter with `env`; return (ok, output)."""
    full_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DJANGO_", "SITE_", "NEWSDESK_"))
    }
    full_env.update(env, DJANGO_SETTINGS_MODULE="config.settings")
    code = (
        "from django.conf import settings as s;"
        "print(s.DEBUG, s.SECURE_SSL_REDIRECT, s.SECURE_HSTS_SECONDS, s.SESSION_COOKIE_SECURE,"
        " s.CSRF_TRUSTED_ORIGINS)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], env=full_env, capture_output=True, text=True, cwd=settings.BASE_DIR, timeout=120
    )
    return result.returncode == 0, result.stdout + result.stderr


class DeployedSettingsTests(SimpleTestCase):
    def test_production_settings_are_secure(self):
        ok, output = load_settings(GOOD_PRODUCTION_ENV)
        self.assertTrue(ok, output)
        self.assertEqual(output.strip(), "False True 31536000 True ['https://example.in']")

    def test_staging_starts_with_a_short_hsts(self):
        ok, output = load_settings({**GOOD_PRODUCTION_ENV, "DJANGO_ENV": "staging", "NEWSDESK_WRITER": "fake"})
        self.assertTrue(ok, output)
        self.assertIn("False True 3600 True", output)

    def test_production_refuses_missing_secrets(self):
        env = {**GOOD_PRODUCTION_ENV}
        del env["DJANGO_SECRET_KEY"], env["DJANGO_ALLOWED_HOSTS"]
        ok, output = load_settings(env)
        self.assertFalse(ok)
        self.assertIn("DJANGO_SECRET_KEY must be set", output)
        self.assertIn("DJANGO_ALLOWED_HOSTS must list", output)

    def test_production_refuses_debug_http_and_fake_agents(self):
        ok, output = load_settings(
            {**GOOD_PRODUCTION_ENV, "DJANGO_DEBUG": "1", "SITE_BASE_URL": "http://example.in", "NEWSDESK_WRITER": "fake"}
        )
        self.assertFalse(ok)
        self.assertIn("DJANGO_DEBUG must be off", output)
        self.assertIn("SITE_BASE_URL must be the https://", output)
        self.assertIn("NEWSDESK_WRITER=fake is for development and staging only", output)

    def test_unknown_environment_is_rejected(self):
        ok, output = load_settings({"DJANGO_ENV": "prod"})
        self.assertFalse(ok)
        self.assertIn("DJANGO_ENV must be development, staging or production", output)


@override_settings(ALLOWED_HOSTS=["example.in"], SECURE_SSL_REDIRECT=True)
class HealthCheckTests(TestCase):
    def test_healthy(self):
        with mock.patch("redis.Redis.ping", return_value=True):
            # Plain HTTP and an unlisted host, as Docker and uptime monitors call it.
            response = self.client.get("/healthz/", HTTP_HOST="10.0.0.5:8000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"database": "ok", "redis": "ok"})
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_redis_down(self):
        with mock.patch("redis.Redis.ping", side_effect=redis.ConnectionError("refused")):
            with self.assertLogs("core.middleware", "ERROR"):
                response = self.client.get("/healthz/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"database": "ok", "redis": "error"})

    def test_other_pages_still_validate_host_and_redirect(self):
        self.assertEqual(self.client.get("/robots.txt", HTTP_HOST="evil.example").status_code, 400)
        response = self.client.get("/robots.txt", HTTP_HOST="example.in")
        self.assertRedirects(response, "https://example.in/robots.txt", fetch_redirect_response=False, status_code=301)


class DeployedEnvironmentTests(TestCase):
    @override_settings(DEPLOYED=True, DJANGO_ENV="production")
    def test_seed_demo_refuses_to_run(self):
        with self.assertRaisesMessage(CommandError, "local development only"):
            call_command("seed_demo")
        self.assertFalse(get_user_model().objects.filter(username="admin").exists())

    @override_settings(DJANGO_ENV="staging")
    def test_staging_hides_from_search_engines(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.content.decode(), "User-agent: *\nDisallow: /\n")


@override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3)
class LoginLockoutTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_superuser("chief", "chief@example.in", "right-password-123")

    def login(self, password, ip="203.0.113.7"):
        return self.client.post(
            "/admin/login/", {"username": "chief", "password": password}, HTTP_X_REAL_IP=ip
        )

    def test_repeated_failures_lock_the_account_for_that_address(self):
        for _ in range(3):
            self.login("wrong")
        response = self.login("right-password-123")
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

        # Someone else (another address) is not locked out by the attacker.
        self.assertEqual(self.login("right-password-123", ip="198.51.100.9").status_code, 302)

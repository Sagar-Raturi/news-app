from django.apps import AppConfig


class NewsdeskConfig(AppConfig):
    name = "newsdesk"
    verbose_name = "Newsdesk"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa: F401

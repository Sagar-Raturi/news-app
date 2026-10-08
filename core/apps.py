from django.apps import AppConfig
from django.contrib.staticfiles.apps import StaticFilesConfig


class CoreConfig(AppConfig):
    name = "core"
    default_auto_field = "django.db.models.BigAutoField"


class LedgerStaticFilesConfig(StaticFilesConfig):
    # static/src holds the Tailwind source; only the compiled CSS is served
    # (and the source's `@import "tailwindcss"` breaks hashed file names).
    ignore_patterns = [*StaticFilesConfig.ignore_patterns, "src"]

from django.core.management.base import BaseCommand

from core.newsroom import bootstrap


class Command(BaseCommand):
    help = "Create (or repair) the page tree, newsroom groups and review workflow. Safe to re-run."

    def handle(self, *args, **options):
        result = bootstrap()
        if options["verbosity"] == 0:
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Site ready: {len(result['sections'])} sections, groups "
                f"{result['writers'].name}/{result['editors'].name}, workflow '{result['workflow'].name}'."
            )
        )

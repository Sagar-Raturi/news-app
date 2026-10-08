from django.core.management.base import BaseCommand

from core.launch import MANUAL_CHECKS, launch_checks


class Command(BaseCommand):
    help = "List what is still missing before a public launch; exits with status 1 while anything is."

    def handle(self, *args, **options):
        checks = launch_checks()
        for check in checks:
            if check.ok:
                self.stdout.write(self.style.SUCCESS(f"  OK    {check.label}"))
            else:
                self.stdout.write(self.style.ERROR(f"  TODO  {check.label}") + f"\n        {check.fix}")
        self.stdout.write("\nAlso confirm:")
        for item in MANUAL_CHECKS:
            self.stdout.write(f"  - {item}")
        missing = sum(not check.ok for check in checks)
        if missing:
            self.stdout.write(self.style.WARNING(f"\n{missing} item(s) to do before launch."))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("\nReady to launch."))

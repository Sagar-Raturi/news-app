import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Block until the default database accepts connections."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=60, help="Seconds to wait before giving up")

    def handle(self, *args, **options):
        deadline = time.monotonic() + options["timeout"]
        while True:
            try:
                connections["default"].ensure_connection()
                return
            except OperationalError:
                if time.monotonic() > deadline:
                    raise CommandError("Database not available.")
                self.stdout.write("Waiting for PostgreSQL...")
                time.sleep(1)

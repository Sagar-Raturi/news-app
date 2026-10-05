#!/bin/sh
# Prepares the database before handing over to the container command.
# Set RUN_MIGRATIONS=0 on services (e.g. the Celery worker) that should not
# touch the schema.
set -e

until pg_isready -d "$DATABASE_URL" -q; do
  echo "Waiting for PostgreSQL..."
  sleep 1
done

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
  python manage.py bootstrap_site
  if [ "${SEED_DEMO:-0}" = "1" ]; then
    python manage.py seed_demo --if-empty
  fi
fi

exec "$@"

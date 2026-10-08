#!/bin/sh
# Prepares the database before handing over to the container command.
# Set RUN_MIGRATIONS=0 on services (e.g. the Celery worker) that should not
# touch the schema.
set -e

python manage.py wait_for_db

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  case "${DJANGO_ENV:-development}" in
    staging|production)
      # Print Django's production warnings in the log on every deploy.
      python manage.py check --deploy
      ;;
  esac
  python manage.py migrate --noinput
  python manage.py bootstrap_site
  if [ "${SEED_DEMO:-0}" = "1" ]; then
    python manage.py seed_demo --if-empty
  fi
fi

exec "$@"

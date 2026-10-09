#!/bin/sh
# Restore the database and uploaded images from a backup made by backup.sh.
#
#   sh docker/restore.sh backups/db-2026-10-09-0230.dump [backups/media-2026-10-09-0230.tgz] --yes
#
# REPLACES the current database (and images, if a media file is given). The
# site is stopped while restoring and started again afterwards. Without --yes
# it only says what it would do.
set -eu

cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.production"

DB_FILE=""
MEDIA_FILE=""
CONFIRMED=no
for arg in "$@"; do
  case "$arg" in
    --yes) CONFIRMED=yes ;;
    *.dump) DB_FILE=$arg ;;
    *.tgz) MEDIA_FILE=$arg ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [ -z "$DB_FILE" ] || [ ! -f "$DB_FILE" ]; then
  echo "Usage: sh docker/restore.sh <db-….dump> [media-….tgz] --yes" >&2
  exit 2
fi
if [ -n "$MEDIA_FILE" ] && [ ! -f "$MEDIA_FILE" ]; then
  echo "Media file not found: $MEDIA_FILE" >&2
  exit 2
fi
if [ "$CONFIRMED" != yes ]; then
  echo "This would REPLACE the database with $DB_FILE${MEDIA_FILE:+ and the images with $MEDIA_FILE}."
  echo "Run again with --yes to do it."
  exit 1
fi

echo "Stopping the site..."
$COMPOSE stop caddy web worker

echo "Restoring the database..."
$COMPOSE run --rm -T pgtools sh -c 'pg_restore --clean --if-exists --no-owner --single-transaction -d "$DATABASE_URL"' < "$DB_FILE"

if [ -n "$MEDIA_FILE" ]; then
  # Extracts over the current folder: every image in the backup comes back;
  # files uploaded after the backup stay on disk, unused.
  echo "Restoring uploaded images..."
  $COMPOSE run --rm --no-deps -T --entrypoint tar web xzf - -C /app < "$MEDIA_FILE"
fi

echo "Starting the site..."
$COMPOSE up -d
echo "Restore done. Check the site and the admin."

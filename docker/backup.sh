#!/bin/sh
# Back up the database and uploaded images.
#
#   sh docker/backup.sh            (from the repository folder on the server)
#
# Writes backups/db-<time>.dump and backups/media-<time>.tgz, keeps 7 days of
# them on the server, and copies them to Cloudflare R2 (kept 30 days there)
# when BACKUP_R2_* is set in .env.production. Pings BACKUP_PING_URL when done,
# so a monitor (healthchecks.io) can alert you if a night's backup is missing.
# Run nightly from cron; see .claude/skills/deploy-ledger/SKILL.md.
set -eu

cd "$(dirname "$0")/.."
ENV_FILE=.env.production
COMPOSE="docker compose -f docker-compose.prod.yml --env-file $ENV_FILE"
STAMP=$(date +%Y-%m-%d-%H%M)
DIR=backups

# Read one variable from the env file without executing it.
setting() {
  grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'
}

mkdir -p "$DIR"
chmod 700 "$DIR"

echo "Backing up the database..."
$COMPOSE run --rm -T pgtools sh -c 'pg_dump --format=custom --no-owner "$DATABASE_URL"' > "$DIR/db-$STAMP.dump.part"
mv "$DIR/db-$STAMP.dump.part" "$DIR/db-$STAMP.dump"

echo "Backing up uploaded images..."
$COMPOSE exec -T web tar czf - -C /app media > "$DIR/media-$STAMP.tgz.part"
mv "$DIR/media-$STAMP.tgz.part" "$DIR/media-$STAMP.tgz"

# Keep a week of backups on the server.
find "$DIR" -maxdepth 1 -type f \( -name 'db-*.dump' -o -name 'media-*.tgz' \) -mtime +7 -delete

BUCKET=$(setting BACKUP_R2_BUCKET)
if [ -n "$BUCKET" ]; then
  echo "Copying to Cloudflare R2 ($BUCKET)..."
  # The keys reach rclone as environment variables passed by name only, so
  # they never appear on a command line (visible to `ps`) or in a file.
  export RCLONE_CONFIG_R2_TYPE=s3
  export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
  export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true
  RCLONE_CONFIG_R2_ACCESS_KEY_ID=$(setting BACKUP_R2_ACCESS_KEY_ID)
  RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$(setting BACKUP_R2_SECRET_ACCESS_KEY)
  RCLONE_CONFIG_R2_ENDPOINT=$(setting BACKUP_R2_ENDPOINT)
  export RCLONE_CONFIG_R2_ACCESS_KEY_ID RCLONE_CONFIG_R2_SECRET_ACCESS_KEY RCLONE_CONFIG_R2_ENDPOINT
  RCLONE="docker run --rm -v $(pwd)/$DIR:/data:ro"
  for var in TYPE PROVIDER NO_CHECK_BUCKET ACCESS_KEY_ID SECRET_ACCESS_KEY ENDPOINT; do
    RCLONE="$RCLONE -e RCLONE_CONFIG_R2_$var"
  done
  RCLONE="$RCLONE rclone/rclone:1.68.2"
  $RCLONE copy /data "r2:$BUCKET/ledger" --include "*-$STAMP.*"
  $RCLONE delete "r2:$BUCKET/ledger" --min-age 30d
fi

PING=$(setting BACKUP_PING_URL)
if [ -n "$PING" ]; then
  curl -fsS -m 10 --retry 3 "$PING" > /dev/null
fi

echo "Backup done: $DIR/db-$STAMP.dump, $DIR/media-$STAMP.tgz"

#!/bin/sh
set -eu

BACKUP_FILE="/workspace/backup.backup"
MARKER_FILE="/restore-state/backup_restored"

if [ ! -f "$BACKUP_FILE" ]; then
  echo "Backup file $BACKUP_FILE not found, skipping restore."
  exit 0
fi

if [ -f "$MARKER_FILE" ]; then
  echo "Backup restore already completed earlier, skipping."
  exit 0
fi

echo "Waiting for database to accept connections..."
until pg_isready -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do
  sleep 2
done

echo "Restoring backup from $BACKUP_FILE..."
PGPASSWORD="$POSTGRES_PASSWORD" pg_restore \
  --clean \
  --verbose \
  --no-owner \
  --host=db \
  --username="$POSTGRES_USER" \
  --dbname="$POSTGRES_DB" \
  "$BACKUP_FILE"

touch "$MARKER_FILE"
echo "Backup restore completed."

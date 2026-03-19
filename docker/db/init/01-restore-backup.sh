#!/bin/sh
set -eu

BACKUP_DIR="/project_backups"
BACKUP_FILE="${POSTGRES_BACKUP_FILE:-}"

log() {
  echo "[db-init] $1"
}

restore_backup() {
  file_path="$1"

  case "$file_path" in
    *.sql)
      log "Restoring SQL backup: $(basename "$file_path")"
      psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$file_path"
      ;;
    *.sql.gz)
      log "Restoring compressed SQL backup: $(basename "$file_path")"
      gunzip -c "$file_path" | psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"
      ;;
    *.dump|*.backup|*.tar)
      log "Restoring pg_dump archive: $(basename "$file_path")"
      pg_restore --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$file_path"
      ;;
    *)
      log "Unsupported backup format: $file_path"
      log "Supported formats: .sql, .sql.gz, .dump, .backup, .tar"
      exit 1
      ;;
  esac
}

if [ ! -d "$BACKUP_DIR" ]; then
  log "Backup directory $BACKUP_DIR not found, skipping restore"
  exit 0
fi

if [ -n "$BACKUP_FILE" ]; then
  TARGET_FILE="$BACKUP_DIR/$BACKUP_FILE"

  if [ ! -f "$TARGET_FILE" ]; then
    log "Configured backup file not found: $TARGET_FILE"
    exit 1
  fi

  restore_backup "$TARGET_FILE"
  exit 0
fi

set -- $(find "$BACKUP_DIR" -maxdepth 1 -type f \( -name '*.sql' -o -name '*.sql.gz' -o -name '*.dump' -o -name '*.backup' -o -name '*.tar' \) | sort)

if [ "$#" -eq 0 ]; then
  log "No backup files found in $BACKUP_DIR, skipping restore"
  exit 0
fi

if [ "$#" -gt 1 ]; then
  log "Found multiple backup files in $BACKUP_DIR"
  printf ' - %s\n' "$@"
  log "Set POSTGRES_BACKUP_FILE to the exact filename you want to restore"
  exit 1
fi

restore_backup "$1"

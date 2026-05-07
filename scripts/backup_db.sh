#!/usr/bin/env bash
set -euo pipefail
DB_PATH="${1:-doctrack.db}"
if [ ! -f "$DB_PATH" ]; then
  echo "DB not found at $DB_PATH"; exit 1
fi
TS=$(date +%Y%m%d-%H%M%S)
BACKUP="${DB_PATH}.backup-${TS}"
cp "$DB_PATH" "$BACKUP"
echo "Backup created: $BACKUP"

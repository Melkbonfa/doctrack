#!/usr/bin/env bash
set -euo pipefail
DB_PATH="${1:-doctrack.db}"
LATEST=$(ls -1t "${DB_PATH}".backup-* 2>/dev/null | head -1 || true)
if [ -z "$LATEST" ]; then
  echo "No backup found matching ${DB_PATH}.backup-*"; exit 1
fi
cp "$LATEST" "$DB_PATH"
echo "Restored $DB_PATH from $LATEST"
echo "To revert code changes: git revert <commit>"

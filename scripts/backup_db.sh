#!/bin/bash
# LENS DB backup — uses sqlite3 .backup which is safe with active connections.
# Runs daily via launchd (com.lens.backup.plist).
# Keeps the last 14 daily backups; prunes older ones.

set -e

DB="/Users/stevenhoward/lens/data/lens.db"
BACKUP_DIR="/Users/stevenhoward/lens/backups"
KEEP=14

mkdir -p "$BACKUP_DIR"

TS=$(date +%Y%m%d-%H%M%S)
OUT="$BACKUP_DIR/lens-$TS.db"

echo "[$(date)] Backing up $DB -> $OUT"
/usr/bin/sqlite3 "$DB" ".backup '$OUT'"

# Verify backup
if /usr/bin/sqlite3 "$OUT" "PRAGMA integrity_check" | head -1 | grep -q "^ok$"; then
    SIZE=$(stat -f%z "$OUT")
    echo "[$(date)] OK: $OUT ($((SIZE / 1024 / 1024)) MB)"
else
    echo "[$(date)] BACKUP FAILED INTEGRITY — keeping anyway for inspection"
    mv "$OUT" "$OUT.suspect"
    exit 1
fi

# Prune old backups, keep newest $KEEP
cd "$BACKUP_DIR"
ls -t lens-*.db 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
    echo "[$(date)] Pruning old backup: $old"
    rm -f "$old"
done

echo "[$(date)] Done."

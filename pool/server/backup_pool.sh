#!/bin/bash

# ====== CONFIGURAÇÃO DA VPS ======
POOL_DB="/opt/rckangaroo/pool/server/pool.db"
BACKUP_DIR="/opt/rckangaroo/pool/server/backups"
BACKUP_FILE="$BACKUP_DIR/pool_latest.db"
TEMP_FILE="$BACKUP_DIR/.pool_latest.db.tmp"
LOCK_FILE="$BACKUP_DIR/.backup.lock"
# =================================

mkdir -p "$BACKUP_DIR"
exec 9>"$LOCK_FILE"
flock -n 9 || exit 0
trap 'rm -f "$TEMP_FILE"' EXIT

if [ -f "$POOL_DB" ]; then
    rm -f "$TEMP_FILE"
    python3 - "$POOL_DB" "$TEMP_FILE" <<'PYEOF'
import sqlite3
import sys

source_path, backup_path = sys.argv[1], sys.argv[2]
source = sqlite3.connect(source_path, timeout=60.0)
backup = sqlite3.connect(backup_path)
with backup:
    source.backup(backup)
result = backup.execute("PRAGMA integrity_check").fetchone()[0]
backup.close()
source.close()
if result.lower() != "ok":
    raise SystemExit(f"backup integrity check failed: {result}")
PYEOF
    mv -f "$TEMP_FILE" "$BACKUP_FILE"
    echo "$(date) - Backup SQLite verificado e atualizado: $BACKUP_FILE"
else
    echo "$(date) - Arquivo pool.db nao encontrado em $POOL_DB"
    exit 1
fi

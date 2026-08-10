#!/bin/bash

# ====== CONFIGURAÇÃO DA VPS ======
POOL_DB="/opt/rckangaroo/pool/server/pool.db"
BACKUP_DIR="/opt/rckangaroo/pool/server/backups"
KEEP_LAST=3   # Manter apenas os 3 backups mais recentes (pool.db cresce ~1GB)
# =================================

mkdir -p "$BACKUP_DIR"
DATE=$(date +%Y-%m-%d_%H-%M-%S)

if [ -f "$POOL_DB" ]; then
    cp "$POOL_DB" "$BACKUP_DIR/pool_$DATE.db"
    if [ -f "${POOL_DB}-wal" ]; then
        cp "${POOL_DB}-wal" "$BACKUP_DIR/pool_$DATE.db-wal"
    fi
    ls -t "$BACKUP_DIR"/pool_*.db | tail -n +$((KEEP_LAST + 1)) | xargs -r rm -f
    echo "$(date) - Backup realizado com sucesso: pool_$DATE.db"
else
    echo "$(date) - Arquivo pool.db nao encontrado em $POOL_DB"
fi

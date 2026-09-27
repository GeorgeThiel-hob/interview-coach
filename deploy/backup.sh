#!/usr/bin/env bash
# Nightly encrypted SQLite backup, copied off-server, 14 days kept (spec 12).
# Cron (server): 15 3 * * * /home/<user>/interview-simulator/deploy/backup.sh >> ~/backup.log 2>&1
# Needs: BACKUP_PASSPHRASE_FILE (a file with a long passphrase, chmod 600) and
#        BACKUP_REMOTE (e.g. u123456@u123456.your-storagebox.de:interview-backups), port 23.
set -euo pipefail
cd "$(dirname "$0")"
: "${BACKUP_PASSPHRASE_FILE:?set BACKUP_PASSPHRASE_FILE}"
: "${BACKUP_REMOTE:?set BACKUP_REMOTE}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# online, consistent copy through SQLite's backup API inside the container
docker compose exec -T app python -c "
import sqlite3; src = sqlite3.connect('data/app.db'); dst = sqlite3.connect('data/backup.db')
src.backup(dst); dst.close(); src.close()"
docker compose cp app:/srv/data/backup.db "$WORK/app.db"
docker compose exec -T app rm -f data/backup.db
gpg --batch --yes --pinentry-mode loopback --passphrase-file "$BACKUP_PASSPHRASE_FILE" \
    --symmetric --cipher-algo AES256 -o "$WORK/app-$STAMP.db.gpg" "$WORK/app.db"
scp -P 23 "$WORK/app-$STAMP.db.gpg" "$BACKUP_REMOTE/"
# keep 14 days on the storage box
ssh -p 23 "${BACKUP_REMOTE%%:*}" "ls ${BACKUP_REMOTE#*:}/app-*.db.gpg | sort | head -n -14 | xargs -r rm -f"
echo "backup $STAMP ok"

#!/usr/bin/env bash
# Restore a backup made by backup.sh. Usage: deploy/restore.sh app-YYYYmmdd-HHMMSS.db.gpg
# Test this regularly (M6 acceptance: a restore from backup has been tested).
set -euo pipefail
cd "$(dirname "$0")"
FILE="${1:?usage: restore.sh <backup.db.gpg>}"
: "${BACKUP_PASSPHRASE_FILE:?set BACKUP_PASSPHRASE_FILE}"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
gpg --batch --pinentry-mode loopback --passphrase-file "$BACKUP_PASSPHRASE_FILE" -d -o "$WORK/app.db" "$FILE"
python3 -c "import sqlite3; c = sqlite3.connect('$WORK/app.db'); print('runs:', c.execute('select count(*) from runs').fetchone()[0]); c.execute('pragma integrity_check')"
docker compose stop app
docker compose cp "$WORK/app.db" app:/srv/data/app.db
docker compose start app
echo "restored $FILE"

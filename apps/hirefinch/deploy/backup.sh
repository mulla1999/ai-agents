#!/usr/bin/env bash
# Back up the production database and files together, and keep the last KEEP_DAYS days (default 14).
#
#   apps/hirefinch/deploy/backup.sh                  # from the workspace root on the server
#
# Writes BACKUP_DIR/hirefinch-<timestamp>/{db.dump,files.tgz,SHA256SUMS} (default ./backups, mode 700).
# The encryption key is NOT included on purpose: keep HIREFINCH_ENCRYPTION_KEYS in a password manager.
# Without it, users' saved SMTP passwords and AI keys in the dump cannot be read.
#
# Daily at 02:30, as the deploy user (crontab -e):
#   30 2 * * * cd /opt/hirefinch && apps/hirefinch/deploy/backup.sh >> backups/backup.log 2>&1
# Copy BACKUP_DIR off the server as well (rclone, restic or your provider's snapshots): a backup on the
# same disk does not survive losing that disk.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
BACKUP_DIR="${BACKUP_DIR:-$ROOT/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
C=(docker compose --env-file .env -f apps/hirefinch/docker-compose.yml -f apps/hirefinch/docker-compose.prod.yml)

umask 077
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$BACKUP_DIR/hirefinch-$stamp"
mkdir -p "$out"

"${C[@]}" exec -T db pg_dump -U hirefinch -Fc hirefinch > "$out/db.dump"
# Read the files volume through the backend container, so the volume name does not matter.
"${C[@]}" exec -T backend tar czf - -C /var/lib/hirefinch . > "$out/files.tgz"
[[ -s "$out/db.dump" && -s "$out/files.tgz" ]] || { echo "backup is empty: $out" >&2; exit 1; }
(cd "$out" && sha256sum db.dump files.tgz > SHA256SUMS)

# Keep recent backups only; this deletes nothing except older hirefinch-* folders in BACKUP_DIR.
find "$BACKUP_DIR" -maxdepth 1 -type d -name 'hirefinch-*' -mtime "+$KEEP_DAYS" -print -exec rm -rf {} +
echo "backup written: $out ($(du -sh "$out" | cut -f1))"

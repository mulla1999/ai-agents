#!/usr/bin/env bash
# Deploy or upgrade HireFinch in production.
#
#   apps/hirefinch/deploy/deploy.sh                 # on the server, from the workspace root
#   apps/hirefinch/deploy/deploy.sh user@server     # from your machine: copy this release, then deploy there
#
# Steps: check .env, back up the database and files, build, start (migrations run before the API
# serves), wait until the API is ready and the site answers over HTTPS. If any step fails it stops
# and prints the backend logs; the backup taken first is what you restore from.
#
# REMOTE_DIR (default /opt/hirefinch) sets the workspace path on the server. SKIP_BACKUP=1 skips the
# backup; use it only for the very first deploy, when there is nothing to back up.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
REMOTE_DIR="${REMOTE_DIR:-/opt/hirefinch}"

if [[ $# -ge 1 ]]; then
  target="$1"
  echo "==> copying release to $target:$REMOTE_DIR"
  # The server keeps its own .env and data; never overwrite them from a laptop.
  rsync -az --delete \
    --exclude .env --exclude '.env.*' --exclude .venv --exclude node_modules --exclude dist \
    --exclude 'apps/*/data' --exclude '__pycache__' --exclude '.pytest_cache' --exclude backups \
    "$ROOT/" "$target:$REMOTE_DIR/"
  exec ssh -t "$target" "cd '$REMOTE_DIR' && SKIP_BACKUP='${SKIP_BACKUP:-}' apps/hirefinch/deploy/deploy.sh"
fi

cd "$ROOT"
C=(docker compose --env-file .env -f apps/hirefinch/docker-compose.yml -f apps/hirefinch/docker-compose.prod.yml)

echo "==> checking .env"
[[ -f .env ]] || { echo ".env is missing; see apps/hirefinch/docs/deployment.md" >&2; exit 1; }
if [[ "$(stat -c %a .env)" != "600" ]]; then
  echo ".env must be readable only by its owner: chmod 600 .env" >&2; exit 1
fi
for key in HIREFINCH_DOMAIN HIREFINCH_SECRET_KEY HIREFINCH_ENCRYPTION_KEYS HIREFINCH_DB_PASSWORD HIREFINCH_SUPERADMIN_EMAIL; do
  grep -Eq "^${key}=.+" .env || { echo "$key is not set in .env" >&2; exit 1; }
done
domain="$(grep -E '^HIREFINCH_DOMAIN=' .env | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')"

if [[ -z "${SKIP_BACKUP:-}" ]] && "${C[@]}" ps --status running --services 2>/dev/null | grep -qx db; then
  echo "==> backing up before the upgrade"
  apps/hirefinch/deploy/backup.sh
fi

echo "==> building and starting"
"${C[@]}" up --build -d --remove-orphans

echo "==> waiting for the API (migrations run first)"
for _ in $(seq 1 60); do
  if "${C[@]}" exec -T backend python -c \
      "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3).status != 200)" \
      >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 5
done
if [[ -z "${ready:-}" ]]; then
  echo "!! the API did not become ready. Last backend logs:" >&2
  "${C[@]}" logs --tail 80 backend >&2
  exit 1
fi

echo "==> checking https://$domain"
for _ in $(seq 1 24); do  # the first certificate can take a minute
  if curl -fsS -o /dev/null --max-time 10 "https://$domain/"; then
    echo "==> deployed: https://$domain"
    "${C[@]}" ps
    exit 0
  fi
  sleep 5
done
echo "!! the API is up but https://$domain does not answer. Check DNS, ports 80/443 and: ${C[*]} logs caddy" >&2
exit 1

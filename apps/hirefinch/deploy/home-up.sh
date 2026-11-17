#!/bin/sh
# Start (or update) HireFinch on this PC with docker-compose.home.yml, then print its public address.
#
# Tunnel: Tailscale Funnel when data/tailscale.key holds an auth key (fixed https://hirefinch.<tailnet>.ts.net
# address), otherwise a Cloudflare quick tunnel (free, but a new address each time it restarts).
# HIREFINCH_TUNNEL=cloudflare or =tailscale picks one explicitly.
# Secrets are read from the workspace .env and data/.encryption_key into data/home.env (mode 600); they are
# never printed.
set -eu

HERE=$(cd "$(dirname "$0")/.." && pwd)    # apps/hirefinch
ROOT=$(cd "$HERE/../.." && pwd)           # workspace root
DATA="$HERE/data"
COMPOSE="docker compose -f $HERE/docker-compose.home.yml"
export HOME_UID="$(id -u)" HOME_GID="$(id -g)"

env_value() {  # the value of $1 in the workspace .env, without quotes
    sed -n "s/^$1=//p" "$ROOT/.env" | tail -n 1 | sed 's/^["'\'']//; s/["'\'']$//'
}

write_env() {  # $1: public URL
    umask 077
    {
        echo "HIREFINCH_PUBLIC_URL=$1"
        echo "HIREFINCH_SECRET_KEY=$(env_value HIREFINCH_SECRET_KEY)"
        echo "HIREFINCH_SUPERADMIN_EMAIL=$(env_value HIREFINCH_SUPERADMIN_EMAIL)"
        echo "HIREFINCH_ENCRYPTION_KEYS=$(cat "$DATA/.encryption_key")"
        [ -s "$DATA/tailscale.key" ] && echo "TS_AUTHKEY=$(cat "$DATA/tailscale.key")"
        true
    } > "$DATA/home.env.tmp"
    mv "$DATA/home.env.tmp" "$DATA/home.env"
}

# Fresh settings (the tunnel reads its key from here); the address is filled in once the tunnel reports it.
write_env "$(cat "$DATA/public_url" 2>/dev/null || echo http://localhost:4173)"
mkdir -p "$DATA/tailscale"

# The old hand-started containers would hold the ports.
docker rm -f hirefinch-web hirefinch-tunnel >/dev/null 2>&1 || true

TUNNEL="${HIREFINCH_TUNNEL:-$([ -s "$DATA/tailscale.key" ] && echo tailscale || echo cloudflare)}"
if [ "$TUNNEL" = tailscale ]; then
    $COMPOSE --profile tailscale up -d tailscale
    $COMPOSE stop cloudflare >/dev/null 2>&1 || true
    url=""
    for _ in $(seq 1 60); do
        host=$($COMPOSE exec -T tailscale tailscale status --json --peers=false 2>/dev/null \
            | sed -n 's/.*"DNSName": *"\([^"]*\)\.".*/\1/p' | head -n 1)
        [ -n "$host" ] && url="https://$host" && break
        sleep 2
    done
else
    $COMPOSE --profile tailscale stop tailscale >/dev/null 2>&1 || true
    $COMPOSE --profile cloudflare up -d cloudflare
    url=""
    for _ in $(seq 1 60); do
        url=$($COMPOSE logs cloudflare 2>&1 | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -n 1 || true)
        [ -n "$url" ] && break
        sleep 2
    done
fi
[ -n "$url" ] || { echo "the tunnel did not report its address; see: $COMPOSE logs" >&2; exit 1; }

write_env "$url"
$COMPOSE up -d --build api web
echo "$url" > "$DATA/public_url"
echo "HireFinch: $url"

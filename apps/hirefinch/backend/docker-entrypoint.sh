#!/bin/sh
# Apply migrations, then serve. Startup recovery (interrupted submissions) runs inside the app.
set -e

alembic upgrade head

# Reachable only through the nginx container on the private compose network.
exec uvicorn --factory hirefinch.app:create_app \
    --host 0.0.0.0 --port 8000 \
    --proxy-headers --forwarded-allow-ips="*" \
    --no-server-header

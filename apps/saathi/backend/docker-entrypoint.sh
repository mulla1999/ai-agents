#!/bin/sh
# Apply migrations, add any new seed schemes, then serve.
set -e

alembic upgrade head
saathi seed

# The backend is reachable only through the nginx container on the private compose network,
# so trusting its X-Forwarded-* headers (for client IPs in OTP rate limits) is safe here.
exec uvicorn --factory saathi.app:create_app \
    --host 0.0.0.0 --port 8000 \
    --proxy-headers --forwarded-allow-ips="*" \
    --no-server-header

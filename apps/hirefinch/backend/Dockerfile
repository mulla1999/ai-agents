# Build context: the workspace root (the backend depends on libs/agents-core).
#   docker build -f apps/hirefinch/backend/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HIREFINCH_DATA_DIR=/var/lib/hirefinch/data \
    HIREFINCH_ARTIFACTS_DIR=/var/lib/hirefinch/artifacts

# TrueType fonts so generated PDFs embed real, selectable text; poppler for page previews.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-liberation poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY libs/agents-core libs/agents-core
COPY apps/hirefinch/backend apps/hirefinch/backend
RUN pip install "./libs/agents-core[all]" "./apps/hirefinch/backend" \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin hirefinch \
    && mkdir -p /var/lib/hirefinch && chown hirefinch /var/lib/hirefinch

USER hirefinch
WORKDIR /app/apps/hirefinch/backend
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]

# Build context: the workspace root (the backend depends on libs/agents-core).
#   docker build -f apps/saathi/backend/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SAATHI_SCHEMES_DIR=/app/apps/saathi/backend/data/schemes

# ffmpeg converts WhatsApp voice notes (OGG/Opus) for speech-to-text and back.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY libs/agents-core libs/agents-core
COPY apps/saathi/backend apps/saathi/backend
RUN pip install "./libs/agents-core[all]" "./apps/saathi/backend" \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin saathi

USER saathi
WORKDIR /app/apps/saathi/backend
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]

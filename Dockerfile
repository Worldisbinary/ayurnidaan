# syntax=docker/dockerfile:1.7
# Production image for the clinical API (patients / practitioners).
# The engine runs on the committed, PII-free knowledge_pack/ - no raw data in the image.
#
# Base image is pinned by digest (reproducible, tamper-evident); Dependabot bumps it.

FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f AS build
WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip wheel --wheel-dir /wheels ".[api]"

FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.title="ayurnidaan-api" \
      org.opencontainers.image.description="Ayurvedic screening and clinical decision-support API" \
      org.opencontainers.image.source="https://github.com/Worldisbinary/ayurnidaan" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.revision="${GIT_SHA}"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AYUR_KNOWLEDGE_DIR=/app/knowledge_pack AYUR_GIT_SHA=${GIT_SHA} PORT=8000
WORKDIR /app

# OS security fixes released since the base image was built; no extra packages.
# hadolint ignore=DL3005
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin ayur

COPY --from=build /wheels /wheels
# pip itself is upgraded so the image does not ship a pip with known CVEs.
# hadolint ignore=DL3013
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir /wheels/*.whl \
 && rm -rf /wheels
COPY --chown=ayur:ayur knowledge_pack ./knowledge_pack
COPY --chown=ayur:ayur migrations ./migrations
COPY --chown=ayur:ayur alembic.ini docker-entrypoint.sh ./
RUN chmod 0555 docker-entrypoint.sh && chown ayur:ayur /app
USER 10001

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=3)"]

ENTRYPOINT ["./docker-entrypoint.sh"]

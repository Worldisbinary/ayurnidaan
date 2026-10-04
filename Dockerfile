# syntax=docker/dockerfile:1.7
# Production image for the clinical API (patients / practitioners).
# The engine runs on the committed, PII-free knowledge_pack/ - no raw data in the image.

FROM python:3.12-slim AS build
WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip wheel --wheel-dir /wheels ".[api]"

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    AYUR_KNOWLEDGE_DIR=/app/knowledge_pack PORT=8000
WORKDIR /app
RUN useradd --create-home --uid 10001 ayur
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
COPY knowledge_pack ./knowledge_pack
COPY migrations ./migrations
COPY alembic.ini ./
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh && chown -R ayur:ayur /app
USER ayur

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=3)" || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]

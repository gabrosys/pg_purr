# syntax=docker/dockerfile:1.7

ARG PG_VERSION=17

############################
# Stage 1 — builder
############################
FROM postgres:${PG_VERSION}-bookworm AS builder

ARG PG_VERSION
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VENV=/opt/pg_purr/.venv \
    PATH=/opt/pg_purr/.venv/bin:$PATH

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        postgresql-plpython3-${PG_VERSION} \
        python3-venv \
        python3-pip \
        python3-dev \
        build-essential \
        libpq-dev \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN python3 -m venv "${VENV}"

COPY docker/requirements.txt /tmp/requirements.txt
RUN pip install --require-hashes --no-deps -r /tmp/requirements.txt

COPY pyproject.toml README.md /opt/pg_purr/
COPY pg_purr/ /opt/pg_purr/pg_purr/
RUN pip install --no-deps /opt/pg_purr/

############################
# Stage 2 — runtime
############################
FROM postgres:${PG_VERSION}-bookworm AS runtime

ARG PG_VERSION
ARG VCS_REF=unknown
ARG BUILD_DATE=1970-01-01T00:00:00Z
ARG VERSION=0.2.0

LABEL org.opencontainers.image.title="pg_purr" \
      org.opencontainers.image.description="PostgreSQL Unified Random & Routing" \
      org.opencontainers.image.source="https://github.com/gabrosys/pg_purr" \
      org.opencontainers.image.url="https://github.com/gabrosys/pg_purr" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.base.name="docker.io/library/postgres:${PG_VERSION}-bookworm"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        postgresql-plpython3-${PG_VERSION} \
        python3 \
        libpq5 \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

ENV VENV=/opt/pg_purr/.venv \
    PATH=/opt/pg_purr/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder --chown=postgres:postgres /opt/pg_purr/.venv /opt/pg_purr/.venv

COPY --chown=postgres:postgres pg_purr.control /usr/share/postgresql/${PG_VERSION}/extension/
COPY --chown=postgres:postgres sql/extension/pg_purr--*.sql /usr/share/postgresql/${PG_VERSION}/extension/

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
    CMD pg_isready -U "${POSTGRES_USER:-postgres}" || exit 1

############################
# Stage 3 — test
############################
FROM runtime AS test

USER root
COPY docker/requirements-dev.txt /tmp/requirements-dev.txt
RUN /opt/pg_purr/.venv/bin/pip install --require-hashes --no-deps \
        -r /tmp/requirements-dev.txt
COPY --chown=postgres:postgres tests/ /opt/pg_purr/tests/
USER postgres

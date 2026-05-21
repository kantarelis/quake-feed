# Single image used by the backend, Celery worker, and Celery beat services.
# Docker Compose selects the entrypoint per service; the image is identical.
# The dev/test stack (linters + pytest) is installed so `make test` can be
# executed in-container without juggling a second image.

# ---------------------------------------------------------------------------
# Stage 1: build the React/Vite SPA. The compiled bundle is copied into the
# Python runtime stage below; Node itself never ships in the final image.
# ---------------------------------------------------------------------------
FROM node:20-slim AS frontend-build

WORKDIR /frontend

# Install against the committed lockfile first so the dependency layer is
# reused across source-only rebuilds.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Python runtime.
# ---------------------------------------------------------------------------
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System dependencies: build-essential + libpq-dev cover the psycopg source
# build when no binary wheel is published for the target Python version.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the requirement chain first so the dependency layer is reused across
# source-only rebuilds.
COPY requirements.txt requirements-test.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY . .

# Pull in the SPA built in stage 1. FastAPI serves this at / (quake/main.py);
# frontend/ source is .dockerignored, so this is the only frontend in the image.
COPY --from=frontend-build /frontend/dist ./frontend/dist

# Drop privileges: create a system user, hand ownership of /app to it, switch.
RUN groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app appuser \
    && chown -R appuser:appuser /app

USER appuser

CMD ["python", "__main__.py"]

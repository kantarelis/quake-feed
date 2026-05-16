# Single image used by the backend, Celery worker, and Celery beat services.
# Docker Compose selects the entrypoint per service; the image is identical.
# The dev/test stack (linters + pytest) is installed so `make test` can be
# executed in-container without juggling a second image.

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

# Drop privileges: create a system user, hand ownership of /app to it, switch.
RUN groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app appuser \
    && chown -R appuser:appuser /app

USER appuser

CMD ["python", "__main__.py"]

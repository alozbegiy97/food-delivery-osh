# syntax=docker/dockerfile:1

# ---------- base: Python + uv, dependencies resolved from uv.lock ----------
FROM python:3.14.10-slim-trixie AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

RUN pip install --no-cache-dir uv==0.13.4

WORKDIR /app
COPY pyproject.toml uv.lock ./

# ---------- dev: all dependency groups, code is bind-mounted ----------
FROM base AS dev
RUN uv sync --frozen --no-install-project
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "app", "--no-access-log"]

# ---------- prod (demo): runtime dependencies only, non-root user ----------
FROM base AS prod
RUN uv sync --frozen --no-install-project --no-dev \
    && useradd --create-home --uid 10001 app
COPY --chown=app:app . .
# Mount point of the media-data volume (DEC-145). A new named volume copies
# the owner of this directory, so the non-root user can store uploads.
RUN mkdir -p /app/media && chown app:app /app/media
USER app
EXPOSE 8000
# One process, one Uvicorn worker (DEC-95): slowapi counters live in memory.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]

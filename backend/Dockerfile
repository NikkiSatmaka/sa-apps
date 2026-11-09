# ============================================
# Multi-stage Dockerfile untuk FastAPI Backend
# Package manager: uv (uv.lock sebagai sumber kebenaran dependency)
# Target: Python 3.14 Slim, image < 500MB
# ============================================

# --- Stage 1: Builder ---
FROM python:3.14-slim AS builder

# Copy binary uv dari image resmi Astral (versi di-pin untuk reproducibility).
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /uvx /bin/

WORKDIR /app

# Install build dependencies (gcc + libpq untuk kompilasi asyncpg dsb).
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Konfigurasi uv:
# - UV_COMPILE_BYTECODE: pre-compile .pyc untuk startup lebih cepat.
# - UV_LINK_MODE=copy: hindari warning hardlink lintas filesystem di Docker.
# - UV_PYTHON_DOWNLOADS=0: pakai Python dari base image, jangan download.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# Layer 1: install HANYA dependency (tanpa source project) dari uv.lock.
# Di-cache selama lockfile tidak berubah — rebuild source tak re-install deps.
# --frozen: wajib persis sesuai uv.lock, gagal kalau lock out-of-date.
# --no-dev: skip dependency group dev (pytest/ruff/dll) di image produksi.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

# Layer 2: copy source lalu install project itu sendiri ke .venv.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# --- Stage 2: Runtime ---
FROM python:3.14-slim AS runtime

WORKDIR /app

# Runtime dependencies: libpq5 untuk asyncpg, curl untuk healthcheck.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/* && \
    # User non-root untuk keamanan.
    adduser --disabled-password --gecos "" appuser

# Copy virtualenv (berisi deps + project) dan source dari builder.
COPY --from=builder --chown=appuser:appuser /app /app

# Pakai binary dari .venv tanpa perlu aktivasi manual.
ENV PATH="/app/.venv/bin:$PATH"

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=40s \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

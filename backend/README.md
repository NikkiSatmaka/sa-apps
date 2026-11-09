# Portal SA — Backend

Backend API untuk Portal SA: manajemen proyek pre-sales dan pencatatan aktivitas harian Solutions Architect. Dibangun dengan **FastAPI** (Python 3.12) di atas PostgreSQL.

Untuk gambaran produk, fitur, dan arsitektur menyeluruh, lihat [README root](../README.md). Untuk workflow kontribusi (branching, commit, verification gate, migration), lihat [CONTRIBUTING.md](../CONTRIBUTING.md).

## Struktur

- `app/api` — router FastAPI (satu modul per domain).
- `app/services` — business logic.
- `app/models` — model SQLAlchemy.
- `app/schemas` — schema Pydantic (request/response).
- `app/core` — config, database, middleware, dependencies.
- `alembic/` — migration database (Alembic).
- `tests/` — test suite (pytest).

## Toolchain & dependency

Project ini uv-native. `pyproject.toml` adalah sumber kebenaran dependency, `uv.lock` mem-pin versi exact untuk reproducibility.

```bash
# Pasang semua dependency (termasuk dev group) ke .venv
uv sync

# Hanya runtime (seperti build produksi)
uv sync --no-dev

# Tambah / hapus dependency
uv add <paket>
uv remove <paket>
```

## Development

```bash
# Jalankan test suite
uv run pytest

# Lint
uv run ruff check .

# Jalankan dev server
uv run uvicorn app.main:app --reload
```

## Migration

Setiap perubahan model SQLAlchemy wajib disertai migration Alembic di `alembic/versions/` dalam PR yang sama.

```bash
# Generate migration dari perubahan model
uv run alembic revision --autogenerate -m "deskripsi"

# Terapkan migration
uv run alembic upgrade head
```

## Verification gate

Sebelum membuka PR: test suite lolos (`uv run pytest`) dan app bisa di-import bersih (`uv run python -c "import app.main"`). Detail di [CONTRIBUTING.md](../CONTRIBUTING.md).

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
# Jalankan test suite (±9 detik; DATABASE_URL dipaksa ke target yang gagal cepat di conftest,
# jadi test unit tidak pernah menyentuh database nyata)
uv run pytest

# Laporan cakupan baris + cabang per modul (konfigurasi di [tool.coverage] pyproject.toml)
uv run pytest --cov --cov-report=term-missing
# Laporan HTML: tambahkan --cov-report=html (hasil di htmlcov/)

# Audit durasi test paling lambat
uv run pytest --durations=10

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

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

## Test integrasi (Postgres nyata)

Test di `tests/integration/` (marker `integration`) berjalan terhadap Postgres 18 sungguhan:
test migration (upgrade/downgrade/data), constraint database, dan jalur API end-to-end. Default
`uv run pytest` **hanya menjalankan test unit** (`addopts = "-m 'not integration'"`); integrasi dipilih
eksplisit dan **dilewati dengan pesan jelas** bila `TEST_DATABASE_URL` tidak di-set.

```bash
# 1. Postgres 18 sementara (terpisah dari stack Compose & database dev; hilang saat dihentikan)
docker run -d --rm --name sa-test-pg -e POSTGRES_PASSWORD=test \
  -p 127.0.0.1:55432:5432 --tmpfs /var/lib/postgresql postgres:18-alpine
docker exec sa-test-pg pg_isready -U postgres   # tunggu "accepting connections"

# 2. Jalankan test integrasi (URL menunjuk SERVER; fixture membuat database acak sa_test_<hex>)
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@127.0.0.1:55432/postgres
uv run pytest -m integration

# 3. Bersihkan
docker rm -f sa-test-pg
```

Cara kerja fixture (`tests/integration/conftest.py`):

- Fixture sesi membuat database `sa_test_<hex>` di server itu, menjalankan `alembic upgrade head`
  (subprocess dengan `DATABASE_URL` diarahkan ke database sementara), dan menghapusnya di akhir.
  Hanya database buatan fixture yang dihapus; `DATABASE_URL` dev/Compose tidak pernah dipakai.
- Isolasi per test: transaksi yang di-rollback; `commit()` pada kode produksi menjadi savepoint.
- Klien API (`api`): `httpx.AsyncClient` + `ASGITransport` dengan override `get_db` ke sesi test dan
  `AsyncSessionLocal` di-patch di semua modul `app.*` yang membuka sesinya sendiri
  (`patch_session_factory`). Event startup (scheduler SLA, sweep Requirement) tidak jalan, dan background
  task generate Requirement diganti mock (Gemini nyata tidak pernah dipanggil; fake LLM/Drive/Gmail/Calendar
  ada di tiket #54).
- Keamanan: `TEST_DATABASE_URL` wajib driver `postgresql+asyncpg` dan host lokal (`127.0.0.1`/`localhost`).
  Untuk server uji non-lokal (mis. service CI) set `TEST_DATABASE_ALLOW_REMOTE=1`.

### Fake boundary (Gemini, Drive, Gmail, Calendar)

Fake di `tests/integration/fakes/` menggantikan layanan eksternal pada test integrasi. Fixture
(`fake_llm`, `fake_drive`, `fake_gmail`, `fake_calendar`) terdaftar otomatis di `tests/integration/`,
dibuat baru per test, dan dipulihkan oleh `monkeypatch` (tanpa state sisa). Tidak ada perubahan
kode produksi: semua dipasang pada singleton/registry yang sudah ada.

| Fixture | Dipasang di | Pemrograman | Perekaman |
|---|---|---|---|
| `fake_llm` | `llm_factory` (adapter `fake`, `LLM_PROVIDER=fake`) | `sukses/malformed/error(tipe)/terpotong(jenis, ...)`, `program(jenis, *respons, tetap=)` | `panggilan`, `jumlah(jenis)`, `panggilan_jenis(jenis)` |
| `fake_drive` | method publik `folder_provisioner` | `fail_next(operasi, times=)`, `fail_always(operasi)` | `panggilan`, `folder`, `izin`, `peran(folder, email)` |
| `fake_gmail` | `notification_service.send_email` | `fail_next(times=)`, `fail_always()`, `terkonfigurasi`, `tahan_email()/lepaskan_email()` | `percobaan`, `terkirim`, `gagal`, `await tunggu_percobaan(n)` |
| `fake_calendar` | `calendar_service.fetch_events` | `set_events(*item)`, `fail_next("timeout"/"api")`, `fail_always()` | `access_token_diterima` |

Catatan:

- `fake_llm` jenis panggilan: `complete_text`, `parse_document`, `structure_text`. Panggilan yang belum
  diprogram gagal keras (`AssertionError`). Mode: sukses, `malformed` (structure_text → error
  `invalid_response`; lainnya → teks JSON rusak), `error` (`timeout`/`auth_error`/`invalid_response`/`unknown`),
  `terpotong` (`finish_reason="MAX_TOKENS"`).
- `fake_gmail.send_email` meniru kontrak produksi: gagal = `False`, tidak raise; `EMAIL_RETRY_INTERVAL`
  dinolkan. Email dikirim di background task bersesi sendiri; pada harness satu koneksi, panggil
  `tahan_email()` sebelum request dan `lepaskan_email()` sesudahnya agar tidak bertabrakan dengan sesi request.
- `fake_calendar` menerima item mentah gaya Google (`event_berjadwal`, `event_seharian`) dan memakai
  `_parse_event` asli.
- Contoh: `tests/integration/test_fake_boundary_contoh.py` (lewat API + Postgres) dan
  `tests/test_fakes_boundary.py` (unit perilaku fake).

## Gerbang cakupan (setara CI)

CI memblok bila cakupan **gabungan unit + integrasi** punya baris < 90% atau cabang < 80%
(CONSTRAINTS.md). Cara menjalankan hal yang sama secara lokal (Postgres sementara dari bagian
di atas harus hidup, `TEST_DATABASE_URL` di-set):

```bash
cd backend
export COVERAGE_FILE=cov-unit.data
uv run pytest -q -W ignore --cov=app --cov-branch --cov-report=
export COVERAGE_FILE=cov-integrasi.data
uv run pytest -q -W ignore -m integration --cov=app --cov-branch --cov-report=

export COVERAGE_FILE=cov-gabungan.data
uv run coverage combine --keep cov-unit.data cov-integrasi.data
uv run coverage report --skip-empty                 # tabel per modul + kolom Missing
uv run coverage json -o coverage.json
uv run python scripts/cakupan_gerbang.py coverage.json   # exit 0 = lolos, 1 = gagal
```

Berkas `cov-*.data`/`coverage.json` adalah artefak lokal; jangan di-commit. Cara membaca
kegagalan: CONSTRAINTS.md bagian 6. Skrip gerbang punya test unit
(`tests/test_cakupan_gerbang.py`).

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
